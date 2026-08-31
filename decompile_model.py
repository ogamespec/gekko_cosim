#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decompile_model.py -- decompilation of the native code of COSIM.m2630opt.Jul1599
================================================================================
The model is compiled logic of the GKO processor (PowerPC). Its executable
code is a flat sequence of linear "evaluation cells":

  * combinational cones:  lbz (inputs) -> and/or/nor (SOP) -> stb (output);
  * bit packing:          slwi/rlwimi assemble 32-bit vectors from wires;
  * priority decoders:    cmplw/cmplwi + bne/b -- cascades of if/else-if
                          that set control wires and constants;
  * latches / state:      stw/sth/stb 32/16/8-bit values.

The decompiler executes the code symbolically: registers -> expressions over
wires w(bank, offset), constants and boolean operations; on store
instructions it emits Verilog-style pseudocode.

State banks (bootstrap base registers): r13..r20 = 8 banks of 0x10000 bytes.

Patch slots: the code region is divided into 0x80-byte cells; the first word
of every cell is a patch-list node. MVLSIM patches 'ppc'-type models by
overwriting every node with 0x60000000 (nop), so those words decode as a
`nop` and are printed as "[patch slot] nop".

Usage:
    python3 decompile_model.py                 # built-in demo regions
    python3 decompile_model.py 0xSTART 0xEND   # one custom region
    python3 decompile_model.py 0xS 0xE "label" # custom region with a label
"""
import struct
import sys

from capstone import Cs, CS_ARCH_PPC, CS_MODE_BIG_ENDIAN, CS_MODE_32

MODEL = "model/COSIM.m2630opt.Jul1599"
OUT = "model/COSIM.m2630opt.Jul1599.pseudo.txt"
md = Cs(CS_ARCH_PPC, CS_MODE_BIG_ENDIAN | CS_MODE_32)
md.detail = False

BANKS = {13: 0, 14: 1, 15: 2, 16: 3, 17: 4, 18: 5, 19: 6, 20: 7}

# ---------------------------------------------------------------------------
# Symbolic values
# ('W', bank, off)        -- 1-bit wire
# ('C', int)              -- constant
# ('NOT', e), ('AND',a,b), ('OR',a,b), ('XOR',a,b)
# ('PACK', [(bit, expr),...]) -- 32-bit value with known bits
# ('UNK',)
# ---------------------------------------------------------------------------

def simpl(e):
    t = e[0]
    if t == 'NOT':
        x = simpl(e[1])
        if x[0] == 'C': return ('C', 1 - x[1])
        if x[0] == 'NOT': return x[1]
        return ('NOT', x)
    if t == 'AND':
        a, b = simpl(e[1]), simpl(e[2])
        if a[0] == 'C':
            return ('C', 0) if a[1] == 0 else b
        if b[0] == 'C':
            return ('C', 0) if b[1] == 0 else a
        if a == b: return a
        if a[0] == 'NOT' and a[1] == b: return ('C', 0)
        if b[0] == 'NOT' and b[1] == a: return ('C', 0)
        return ('AND', a, b)
    if t == 'OR':
        a, b = simpl(e[1]), simpl(e[2])
        if a[0] == 'C':
            return ('C', 1) if a[1] == 1 else b
        if b[0] == 'C':
            return ('C', 1) if b[1] == 1 else a
        if a == b: return a
        if a[0] == 'NOT' and a[1] == b: return ('C', 1)
        if b[0] == 'NOT' and b[1] == a: return ('C', 1)
        return ('OR', a, b)
    if t == 'XOR':
        a, b = simpl(e[1]), simpl(e[2])
        if a[0] == 'C':
            return ('NOT', b) if a[1] == 1 else b
        if b[0] == 'C':
            return ('NOT', a) if b[1] == 1 else a
        if a == b: return ('C', 0)
        return ('XOR', a, b)
    return e


import pickle as _pickle

def _load_slotmap():
    """Build the slot->name map directly from the model file (symbol table).
    Class 0x70050000: slot = word1_lo; class 0x02040000: slot = (byte8<<8)|word1_lo.
    Names are reconstructed by prefix compression (keep)."""
    try:
        data = open(MODEL, 'rb').read()
    except Exception:
        return {}
    sec = data[0x4BA840:0x4BA840 + 0x5B76C]
    recs = []
    i = 0
    while i < len(sec) - 16:
        w0 = struct.unpack('>I', sec[i:i+4])[0]
        if w0 == 0x70050000:
            w1 = struct.unpack('>I', sec[i+4:i+8])[0]
            keep = sec[i+10]; ns = i+11; kind = 'A'
        elif w0 == 0x02040000:
            w1 = struct.unpack('>I', sec[i+4:i+8])[0]
            keep = sec[i+9]; ns = i+10; kind = 'B'
        else:
            i += 1; continue
        j = ns
        while j < len(sec) and 32 <= sec[j] < 127:
            j += 1
        if j < len(sec) and sec[j] == 0 and 1 <= j-ns <= 48:
            recs.append((w0, w1, sec[i+8] if kind == 'B' else None, keep,
                         sec[ns:j].decode('latin1'), kind))
            i = j+1
        else:
            i += 1
    full = None
    slotmap = {}
    for w0, w1, b8, keep, nm, kind in recs:
        if keep == 0:
            full = nm
        elif full and keep <= len(full):
            full = full[:keep] + nm
        else:
            full = (full + '.' + nm) if full else None
        slot = (w1 & 0xFFFF) if kind == 'A' else ((b8 << 8) | (w1 & 0xFF))
        slotmap.setdefault(slot, full)
    return slotmap

_SLOTMAP = _load_slotmap()

def slot_name(bank, off):
    """Name of the wire at (bank, offset): slot = off (>=0) or off+0x10000."""
    s = off if off >= 0 else off + 0x10000
    return _SLOTMAP.get(s)

def fmt(e, names=None):
    """Format an expression into a readable form."""
    t = e[0]
    if t == 'W':
        b, o = e[1], e[2]
        name = slot_name(b, o)
        if name:
            return name
        return "w[%d][%s]" % (b, ("%04x" % (o & 0xFFFF)) if o >= 0 else ("-%04x" % (-o & 0xFFFF)))
    if t == 'C':
        v = e[1]
        if v == 0: return "0"
        if v == 1: return "1"
        if v > 0xFFFF:
            return "0x%08x" % v
        return "0x%x" % v
    if t == 'REG':
        return "r%d" % e[1]
    if t == 'NOT':
        x = fmt(e[1], names)
        if x.startswith('(') or x.startswith('~'):
            return "~%s" % x
        return "~(%s)" % x
    if t == 'AND':
        return "(%s & %s)" % (fmt(e[1], names), fmt(e[2], names))
    if t == 'OR':
        return "(%s | %s)" % (fmt(e[1], names), fmt(e[2], names))
    if t == 'XOR':
        return "(%s ^ %s)" % (fmt(e[1], names), fmt(e[2], names))
    if t == 'PACK':
        parts = []
        for bit, x in sorted(e[1], reverse=True):
            parts.append("%d:%s" % (bit, fmt(x, names)))
        return "{%s}" % ", ".join(parts)
    if t == 'LD32':
        return "mem32[%d][%s]" % (e[1], ("%04x" % (e[2] & 0xFFFF)) if e[2] >= 0 else "-%04x" % (-e[2] & 0xFFFF))
    return "??"


def fmt_off(o):
    """State offset (for a store destination)."""
    return ("%04x" % (o & 0xFFFF)) if o >= 0 else ("-%04x" % (-o & 0xFFFF))


# ---------------------------------------------------------------------------
# Decompiler
# ---------------------------------------------------------------------------
class Decomp:
    def __init__(self, data, names=None):
        self.data = data
        self.regs = {i: ('REG', i) for i in range(32)}
        self.names = names or {}
        self.out = []
        self.pending_cmp = None
        self.if_stack = []      # (bne_target, indent, else_open, cond_str, prev_cond)
        self.indent = 0
        self.events = []        # ('IF'|'ELSEIF'|'ELSE'|'ENDIF'|'STORE'|'NOTE', ...)
        self.cur_cond = ('C', 1)
        self.record = True

    def ev(self, e):
        if self.record:
            self.events.append(e)

    def wr(self, s=""):
        self.out.append("  " * self.indent + s)

    def reg(self, i):
        return self.regs.get(i, ('UNK',))

    def decode(self, addr):
        try:
            return next(md.disasm(self.data[addr:addr+4], addr))
        except StopIteration:
            return None

    def close_done_ifs(self, ip):
        """Close ifs whose bne target has already been passed (the else
        branch ended by falling through, without an explicit jump)."""
        while self.if_stack:
            tgt, if_ind, else_open = self.if_stack[-1][:3]
            if ip > tgt or (ip == tgt and not else_open):
                self.indent = if_ind
                self.wr("}")
                self.ev(('ENDIF',))
                self.if_stack.pop()
            else:
                break

    def next_ins(self, addr):
        """Next decodable instruction (skipping patch slots).
        Returns (address, mnemonic, op_str)."""
        for off in range(0, 0x200, 4):
            ins = self.decode(addr + off)
            if ins is not None:
                return (addr + off, ins.mnemonic, ins.op_str)
        return None

    def run(self, start, end, label=""):
        self.wr("// ========== %s: 0x%x..0x%x ==========" % (label, start, end))
        addr = start
        while addr < end:
            self.close_done_ifs(addr)
            # patch-list nodes are NOP'd at load time (0x60000000) for
            # 'ppc'-type models -- they are the seams between cells
            if self.data[addr:addr+4] == b'\x60\x00\x00\x00':
                self.wr("// @%08x: [patch slot] nop" % addr)
                addr += 4
                continue
            ins = self.decode(addr)
            if ins is None:
                self.wr("// @%08x: [non-instruction word / data]" % addr)
                addr += 4
                continue
            m, ops = ins.mnemonic, ins.op_str
            a = addr
            if m in ('lbz', 'lbzu', 'lhz', 'lwz', 'lwzu', 'lha'):
                rd, rest = ops.split(',', 1)
                rest = rest.strip()
                try:
                    d, ra = rest.split('(')
                    ra = ra.rstrip(')')
                    d = int(d, 0)
                except Exception:
                    ra = '0'; d = 0
                ri = int(rd[1:])
                if ra in ('r13', 'r14', 'r15', 'r16', 'r17', 'r18', 'r19', 'r20'):
                    bank = BANKS[int(ra[1:])]
                    if m in ('lwz', 'lwzu'):
                        self.regs[ri] = ('LD32', bank, d)
                    else:
                        self.regs[ri] = ('W', bank, d)
                else:
                    self.regs[ri] = ('UNK',)
            elif m in ('li', 'lis', 'addi', 'addis', 'ori', 'oris', 'xori', 'xoris'):
                parts = [x.strip() for x in ops.split(',')]
                rd = parts[0]
                ri = int(rd[1:])
                if m in ('ori', 'oris', 'xori', 'xoris'):
                    # format: rD, rS, imm -- fold only constants
                    try:
                        v = int(parts[2], 0)
                    except Exception:
                        self.regs[ri] = ('UNK',)
                        addr += 4
                        continue
                    cur = self.reg(ri)
                    if cur[0] == 'C':
                        if m == 'oris': v <<= 16
                        if m == 'xoris': v <<= 16
                        v = (cur[1] | v) if m in ('ori', 'oris') else (cur[1] ^ v)
                        self.regs[ri] = ('C', v & 0xFFFFFFFF)
                    else:
                        self.regs[ri] = ('UNK',)
                else:
                    try:
                        v = int(parts[1], 0)
                    except Exception:
                        v = 0
                    if m in ('addi', 'addis'):
                        cur = self.reg(ri)
                        if cur[0] == 'C':
                            self.regs[ri] = ('C', (cur[1] + v) & 0xFFFFFFFF)
                        else:
                            self.regs[ri] = ('UNK',)
                    else:
                        self.regs[ri] = ('C', v & 0xFFFFFFFF)
            elif m in ('and', 'andc', 'or', 'orc', 'nor', 'nand', 'xor', 'eqv'):
                rd, rest = ops.split(',', 1)
                r1, r2 = [x.strip() for x in rest.split(',')]
                a1, a2 = self.reg(int(r1[1:])), self.reg(int(r2[1:]))
                if m == 'and': v = simpl(('AND', a1, a2))
                elif m == 'andc': v = simpl(('AND', a1, ('NOT', a2)))
                elif m == 'or': v = simpl(('OR', a1, a2))
                elif m == 'orc': v = simpl(('OR', a1, ('NOT', a2)))
                elif m == 'nor': v = simpl(('NOT', ('OR', a1, a2)))
                elif m == 'nand': v = simpl(('NOT', ('AND', a1, a2)))
                elif m == 'xor': v = simpl(('XOR', a1, a2))
                else: v = simpl(('NOT', ('XOR', a1, a2)))
                self.regs[int(rd[1:])] = v
            elif m == 'not':
                rd, r1 = ops.split(',')
                self.regs[int(rd[1:])] = simpl(('NOT', self.reg(int(r1.strip()[1:]))))
            elif m in ('slwi', 'srwi', 'srawi', 'slli', 'rlwinm'):
                # shifts/masks: keep as PACK/UNK
                rd, rest = ops.split(',', 1)
                try:
                    parts = [x.strip() for x in rest.split(',')]
                    rs = int(parts[0][1:])
                    sh = int(parts[1], 0)
                except Exception:
                    rs, sh = 0, 0
                ri = int(rd[1:])
                if m == 'slwi' and self.reg(rs)[0] in ('W', 'NOT', 'AND', 'OR', 'C'):
                    # rD = rS << sh: MSB bit (31-sh) <- source bit 0
                    self.regs[ri] = ('PACK', [(31 - sh, self.reg(rs))])
                else:
                    self.regs[ri] = ('UNK',)
            elif m == 'rlwimi':
                # rA = (rotl(rS,SH) & mask) | (rA & ~mask); with MB==ME==b and
                # SH=31-b: bit b of rA <- source bit 0 (wire into a vector)
                rd, rest = ops.split(',', 1)
                rs, sh, mb, me = [x.strip() for x in rest.split(',')]
                ri = int(rd[1:])
                rs_i = int(rs[1:])
                mb_i = int(mb, 0); me_i = int(me, 0); sh_i = int(sh, 0)
                cur = self.regs.get(ri, ('C', 0))
                if mb_i == me_i and self.reg(rs_i)[0] in ('W', 'NOT', 'AND', 'OR', 'C'):
                    b = 31 - sh_i
                    if cur[0] == 'PACK':
                        bits = [(x, y) for x, y in cur[1] if x != b] + [(b, self.reg(rs_i))]
                    elif cur[0] == 'C':
                        bits = [(x, ('C', (cur[1] >> (31 - x)) & 1)) for x in range(32) if x != b]
                        bits.append((b, self.reg(rs_i)))
                    else:
                        bits = [(b, self.reg(rs_i))]
                    self.regs[ri] = ('PACK', bits)
                else:
                    self.regs[ri] = ('UNK',)
            elif m in ('stb', 'stbu', 'sth', 'stw', 'stwu'):
                rs, rest = ops.split(',', 1)
                rest = rest.strip()
                try:
                    d, ra = rest.split('(')
                    ra = ra.rstrip(')')
                    d = int(d, 0)
                except Exception:
                    ra = '0'; d = 0
                if ra in ('r13', 'r14', 'r15', 'r16', 'r17', 'r18', 'r19', 'r20'):
                    bank = BANKS[int(ra[1:])]
                    v = self.reg(int(rs[1:]))
                    nm = slot_name(bank, d)
                    suffix = ("  // %s" % nm) if nm else ""
                    if m in ('stw', 'stwu'):
                        self.wr("// @%08x:  mem32[%d][%s] <= %s;%s" % (a, bank, fmt_off(d), fmt(v, self.names), suffix))
                        self.ev(('STORE', bank, d, fmt(v, self.names), 32, a))
                    else:
                        self.wr("// @%08x:  w[%d][%s]    <= %s;%s" % (a, bank, fmt_off(d), fmt(v, self.names), suffix))
                        self.ev(('STORE', bank, d, fmt(v, self.names), 1, a))
                else:
                    self.wr("// @%08x:  store %s -> %s(%s)  [base outside the banks]" % (a, rs, d, ra))
            elif m in ('cmplw', 'cmplwi', 'cmpw', 'cmpwi'):
                r1, r2 = [x.strip() for x in ops.split(',')]
                try:
                    lhs = self.reg(int(r1[1:]))
                except Exception:
                    lhs = ('UNK',)
                if r2.startswith('r'):
                    rhs = self.reg(int(r2[1:]))
                else:
                    rhs = ('C', int(r2, 0) & 0xFFFFFFFF)
                self.pending_cmp = (lhs, rhs)
            elif m in ('bne', 'beq'):
                tgt = int(ops, 0)
                if tgt < a:
                    self.wr("// @%08x: %s 0x%x  [backward loop]" % (a, m, tgt))
                    continue
                if self.pending_cmp is not None:
                    lhs, rhs = self.pending_cmp
                    self.pending_cmp = None
                    cond_s = "(%s == %s)" % (fmt(lhs, self.names), fmt(rhs, self.names))
                    if self.if_stack and self.if_stack[-1][2] is True:
                        # we are in the else branch: merge "} else {" + "if (" -> "} else if ("
                        if_ind = self.if_stack[-1][1]
                        self.out[-1] = "  " * if_ind + "else if %s {" % cond_s
                        self.ev(('ELSEIF', cond_s))
                        self.if_stack.append((tgt, if_ind, False, cond_s, self.cur_cond))
                        self.cur_cond = simpl(('AND', self.cur_cond, (lhs, rhs, '==') if False else ('EQ', lhs, rhs))) if False else self.cur_cond
                        self.indent = if_ind + 1
                    else:
                        self.wr("if %s {" % cond_s)
                        self.ev(('IF', cond_s))
                        self.if_stack.append((tgt, self.indent, False, cond_s, self.cur_cond))
                        self.cur_cond = ('EQ', lhs, rhs) if self.cur_cond == ('C', 1) else ('ANDC', self.cur_cond, ('EQ', lhs, rhs))
                        self.indent += 1
                else:
                    self.wr("// @%08x: if(??) goto 0x%x" % (a, tgt))
            elif m == 'b' and ops.startswith('0x'):
                tgt = int(ops, 0)
                if tgt < a:
                    self.wr("// @%08x: goto 0x%x  [backward loop]" % (a, tgt))
                    continue
                if self.if_stack:
                    if_ind = self.if_stack[-1][1]
                    # the chain continues (else) only if the next instruction
                    # is exactly at the bne target
                    nx = self.next_ins(a + 4)
                    if nx and nx[0] == self.if_stack[-1][0]:
                        self.wr("} else {")
                        self.ev(('ELSE',))
                        self.indent = if_ind + 1
                        self.if_stack[-1] = (tgt, if_ind, True, self.if_stack[-1][3], self.if_stack[-1][4])
                    else:
                        self.indent = if_ind
                        self.wr("}")
                        self.ev(('ENDIF',))
                        self.if_stack.pop()
                else:
                    self.wr("// @%08x: goto 0x%x" % (a, tgt))
            elif m.startswith('b') or m.startswith('bc'):
                self.wr("// @%08x: %s %s  [conditional/other branch]" % (a, m, ops))
            addr += 4
        while self.if_stack:
            self.indent -= 1
            self.wr("}")
            self.ev(('ENDIF',))
            self.if_stack.pop()
        self.wr("// end of region")


HEADER = """PSEUDO-DECOMPILATION OF THE NATIVE CODE OF COSIM.m2630opt.Jul1599
============================================================================
The model code is a flat sequence of linear "evaluation cells" of the
compiled GKO processor logic:

  * combinational cones:  w[b][off] <= (term1) | (term2) | ...  (SOP),
    where term = (product of wires) & enable;
  * bit packing:          slwi/rlwimi assemble a 32-bit vector from wires
    {bit:wire, ...};  rlwimi semantics: SH=31-b => bit b <- wire;
  * priority decoders:    if (vector == const) {...} else if (...) {...}
    (vector bits = requests, the test chain = priority selection);
  * multi-bit fields:     mem32[b][off] <= constant (stw 32 bits).

NOTATION:
  w[b][off]     -- 1-bit wire in state bank b (r13..r20 -> 0..7) at offset
                   'off' (hex; negative offsets are relative to the start
                   of the bank, i.e. 0x10000-|off|);
  NAMES: the wire slot = off (>=0) or off+0x10000; names come from the
  model symbol table: class 0x7005 -> slot = word1_lo;
  class 0x0204 -> slot = (byte8 << 8) | word1_lo.
  Named wires print as GKO.<block>...; unnamed ones as w[b][off].
  One wire can be read/written from several banks-planes (two-phase
  two-value simulation: L1/L2 copies) -- in Verilog this is one variable.
  mem32[b][off] -- 32-bit state word (stw);
  rN            -- a register whose value is not tracked (block input);
  {31:w[..], 0:w[..]} -- 32-bit vector assembled from wires;
  [patch slot]  -- a word of the patch list (0x60000000 = nop after load;
                   the code cells step by 0x80 bytes).

VERILOG CORRESPONDENCE (guide):
  1. each wire w[b][off] -> one 1-bit wire/reg variable;
  2. w[b][X] <= expr without self-feedback -> assign;
  3. w[b][X] <= expr that depends on w[b][X] (or is kept between cycles)
     -> always @(posedge clk) / latch;
  4. {bits:wires} == const -> casez/case (priority decoder);
  5. mem32[b][off] -> reg [31:0];
  6. rN (untracked) -- block inputs: name them by meaning (clock/reset/
     enable signals), cross-checking the symbol table.
"""

PATCH_HEAD = 0x4BA800  # head of the patch list (embedded in the code)


def patch_model(raw):
    """Return the runnable code: every patch-list node is overwritten with
    0x60000000 (nop), exactly as MVLSIM patches 'ppc'-type models."""
    code = bytearray(raw)
    h = PATCH_HEAD
    while h >= 4 and h < len(code):
        w = struct.unpack(">I", code[h:h + 4])[0]
        tag = w & 3
        if tag == 0:
            break
        nxt = w & ~3
        code[h:h + 4] = b"\x60\x00\x00\x00"
        if nxt >= h:
            break
        h = nxt
    return bytes(code)


def main():
    data = patch_model(open(MODEL, "rb").read())
    names = {}
    dec = Decomp(data, names)
    out = [HEADER]
    dec.out = out
    regions = [
        (0x40B6AC, 0x40C200, "SOP region 0x40B6AC (combinational logic)"),
        (0x58000, 0x58900, "0x58000: SOP + bit packing (request vector)"),
        (0x58900, 0x59200, "0x58900: priority decoder if/else-if"),
    ]
    if len(sys.argv) >= 3:
        regions = [(int(sys.argv[1], 0), int(sys.argv[2], 0),
                    "region %s..%s" % (sys.argv[1], sys.argv[2]))]
    if len(sys.argv) >= 4:
        regions = [(int(sys.argv[1], 0), int(sys.argv[2], 0), sys.argv[3])]
    for s, e, lab in regions:
        dec.run(s, e, lab)
    text = "\n".join(dec.out)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("written:", OUT, "(%d lines)" % len(dec.out))


if __name__ == "__main__":
    main()
