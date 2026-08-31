#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cosim.py — a limited-but-sufficient interpreter for the MVLSIM model (GKO)
==========================================================================
Runs the logic model of the GKO processor (a PowerPC-class CPU) from a file
like `COSIM.m2630opt.Jul1599` WITHOUT the MVLSIM simulator itself:

    python3 cosim.py -m model/COSIM.m2630opt.Jul1599 \
                     -p model/pin.list \
                     -i inputs.txt -n 100 -o sim.log -d sim.dump

The model is a flat native PowerPC program (type 'ppc'). Every simulation
cycle MVLSIM calls its entry point (header field hdr+0x80):
    * the file starts with `b 0x28`; once patch node 0x28 is NOPed, execution
      falls into bootstrap #1 (0x2C) — the load-time initialization;
    * the per-cycle entry is bootstrap #2 (0x1BCD60): it sets the base
      registers r13..r20 (8 state banks of 0x10000 bytes each), copies the
      MVLSIM function descriptors from the call block, then executes the
      logic "cells" linearly (lbz/andc/or/nor/stb ...), priority decoders
      (cmplw/cmplwi + bne/b), bit packing (slwi/rlwimi), jump-table
      dispatchers (mtlr/blr through callblk+0x10), and the final `blr`
      (0x4BA83C) returns to the caller;
    * assert mechanism: assert cells call the MVLSIM assert printer
      (descriptor in callblk+0x5C, slot 0x805C) via mtlr+blrl; before the
      call they write the MESSAGE OFFSET into slot 0x8040 (callblk+0x40).
      At that offset the model's message region holds "29,<text>\\0" plus
      paths "GKO.<block>:<file>.dsl:<line>\\0".

State model — 8 banks of 0x10000 bytes, one byte per wire, two-value (0/1);
the wire slot is 16-bit: slot = displacement d (d>=0) or d+0x10000 (d<0).
Input pins are applied to the banks before each cycle, outputs are read
afterwards (primary plane — bank 2, base r15).

LIMITATIONS (limited-sufficient):
  * the model's "array" memory (caches/buffers) is zeros (in MVLSIM it is
    owned by the rtx C++ test bench); combinational logic, latches and the
    bus protocol are simulated correctly as long as data comes from the bus
    (DH/DL) via the input map;
  * the initial latch state is zeros plus the bootstrap #1 constants;
  * the exact MVLSIM assert line prefix is simplified; text and path come
    from the model.

INPUT FILE FORMAT (per-cycle pin map):
    # comment
    <cycle>[:<cycle_end>] <PIN>=<value> [<PIN>=<value> ...]
    - value: 0/1 for single-bit pins; 0xNN/NN for buses; '-' = keep previous
    - pins without a value keep their previous value (initially 0)
    - example: 0 SYSCLK=0 HRESET_=1 SRESET_=1 A=0x00000000 DH=0x00000000
               1 SYSCLK=1
    - '*': repeat the previous line for the next cycle

OUTPUT:
    -o log  : simulation log: named signals, asserts, diagnostics;
    -d dump : per-cycle dump of all named slots + pin values (including
              outputs — monitoring);
    --maxasserts N : print details of the first N asserts (default 3);
    --verbose : print the names of known cells on every load/store access
              to a state-bank slot, marked Load/Store;
    --verbose-max N : cap the verbose output per pass.
"""
import argparse
import re
import struct
import sys
import time

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------
HDR_SIZE = 0x9C
ENTRY_EVAL = 0x1BCD60          # per-cycle entry (bootstrap #2)
ENTRY_STAGE3 = 0x2341CC        # per-cycle entry #3: full netlist evaluation
                               # (the real per-cycle flow calls 0x1BCD60 first,
                               #  then 0x2341CC; 0x1BCD60 fast-paths idle cycles)
ENTRY_INIT = 0x2C              # init entry (bootstrap #1)
FINAL_BLR = 0x4BA83C           # last model instruction (return)
CODE_END = 0x4BA840            # end of code (start of the patch list)
RETURN_MARKER = 0xDEADBEEF     # "return to caller" (our LR on entry)
ASSERT_PRINTER = 0x10007624    # MVLSIM function called by the model
MESSAGES_OFF = 0x515FB6        # assert message/path region
MESSAGES_SIZE = 0x624BD
SYM_OFF = 0x4BA840             # symbol table
SYM_SIZE = 0x5B76C
PATCH_HEAD = 0x4BA800          # head of the patch list
STATE_SIZE = 0x500000          # state memory + model arrays (5 MB)
CALLBLK = 0                    # call block at the start of state memory

# MVLSIM function descriptors the bootstrap copies into the call block
# (records: entry, toc) — taken from TOC+0x1A4..+0x1B4 of the mvlsim binary
FUNCDESC = {
    0x00: (ASSERT_PRINTER, 0x2000EFF4),   # assert printer (slot 0x805C)
    0x08: (0x10005C10, 0x2000EFF4),       # .txperf (slot 0x8164)
    0x14: (0x10035A2C, 0x2000EFF4),       # txaa_wr  (slot 0x804C)
    0x18: (0x10033FCC, 0x2000EFF4),       #          (slot 0x8050)
    0x18C: (0x10048958, 0x2000EFF4),      #          (slot 0x8190)
}


# ---------------------------------------------------------------------------
# 1. MODEL: header, patches, symbols, messages, pins
# ---------------------------------------------------------------------------
class Model:
    def __init__(self, path, pinlist_path=None):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        self._hdr()
        self._nop_patches()
        self.slot_names = self._symbols()
        self.messages = self._messages()
        self.pinlist = None
        if pinlist_path:
            self.pinlist = self._pin_list(pinlist_path)
        self.pins = self._pin_table()

    # ---- header (0x9C-byte trailer) ----
    def _hdr(self):
        h = self.data[-HDR_SIZE:]
        self.hdr = {i: struct.unpack(">I", h[i:i + 4])[0] for i in range(0, HDR_SIZE, 4)}
        self.entry = self.hdr.get(0x80) or ENTRY_EVAL
        self.build_date = h[0x28:0x30].decode("latin1").rstrip("\x00")
        self.flags = self.hdr.get(0x18, 0)

    # ---- patch list: all nodes -> NOP (0x60000000) ----
    def _nop_patches(self):
        h = PATCH_HEAD
        n = 0
        code = bytearray(self.data)
        while h >= 4 and h < len(self.data):
            w = struct.unpack(">I", self.data[h:h + 4])[0]
            tag = w & 3
            if tag == 0:
                break
            nxt = w & ~3
            # in the file a node is a link word; in runnable form it is a NOP
            # (for 'ppc'-type models MVLSIM writes 0x60000000 into every node)
            code[h:h + 4] = b"\x60\x00\x00\x00"
            n += 1
            if nxt >= h:
                break
            h = nxt
        self.patch_count = n
        self.code = bytes(code)

    # ---- symbols: slot -> name ----
    def _symbols(self):
        sec = self.data[SYM_OFF:SYM_OFF + SYM_SIZE]
        recs = []
        i = 0
        while i < len(sec) - 16:
            w0 = struct.unpack(">I", sec[i:i + 4])[0]
            if w0 == 0x70050000:
                w1 = struct.unpack(">I", sec[i + 4:i + 8])[0]
                keep = sec[i + 10]
                ns, kind = i + 11, "A"
            elif w0 == 0x02040000:
                w1 = struct.unpack(">I", sec[i + 4:i + 8])[0]
                keep = sec[i + 9]
                ns, kind = i + 10, "B"
            else:
                i += 1
                continue
            j = ns
            while j < len(sec) and 32 <= sec[j] < 127:
                j += 1
            if j < len(sec) and sec[j] == 0 and 1 <= j - ns <= 48:
                recs.append((w0, w1, sec[i + 8] if kind == "B" else None, keep,
                             sec[ns:j].decode("latin1"), kind))
                i = j + 1
            else:
                i += 1
        full = None
        m = {}
        for w0, w1, b8, keep, nm, kind in recs:
            if keep == 0:
                full = nm
            elif full and keep <= len(full):
                full = full[:keep] + nm
            else:
                full = (full + "." + nm) if full else None
            slot = (w1 & 0xFFFF) if kind == "A" else ((b8 << 8) | (w1 & 0xFF))
            m.setdefault(slot, full)
        return m

    def slot_name(self, slot):
        return self.slot_names.get(slot & 0xFFFF)

    # ---- assert messages: offset -> (severity, text, [paths]) ----
    def _messages(self):
        reg = self.data[MESSAGES_OFF:MESSAGES_OFF + MESSAGES_SIZE]
        out = {}
        i = 0
        n = len(reg)
        while i < n:
            j = reg.find(b"\x00", i)
            if j < 0:
                j = n
            s = reg[i:j]
            m = re.match(rb"^(\d+),(.*)$", s, re.S)
            if m:
                sev = int(m.group(1))
                text = m.group(2).decode("latin1", "replace")
                paths = []
                k = j + 1
                while k < n:
                    j2 = reg.find(b"\x00", k)
                    if j2 < 0:
                        j2 = n
                    p = reg[k:j2]
                    if p.startswith(b"GKO."):
                        paths.append(p.decode("latin1", "replace"))
                        k = j2 + 1
                    else:
                        break
                out[i] = (sev, text, paths)
                i = k
            else:
                i = j + 1
        return out

    def assert_at(self, off):
        rec = self.messages.get(off)
        if not rec:
            return None
        sev, text, paths = rec
        path = paths[0] if paths else "GKO.???."
        return (sev, path, text)

    # ---- pin table (after the symbols): name -> [slots] ----
    def _pin_table(self):
        # bounds: first pin header 70 22 00 00 NN after the symbols
        start = self.data.find(b"\x70\x22\x00\x00", SYM_OFF, MESSAGES_OFF - 8)
        if start < 0:
            return {}
        reg = self.data[start:MESSAGES_OFF - 8]
        pins = []          # (bit_count, [slots], name_in_table)
        i, n = 0, len(reg)
        slots = []
        while i < n - 3:
            if reg[i:i + 4] == b"\x70\x22\x00\x00":
                nn = reg[i + 4]
                slots = []
                i += 5
                continue
            b0 = reg[i]
            if b0 == 0x03:                      # LSSD slot record (10 bytes)
                slots.append((reg[i + 8] << 8) | reg[i + 9])
                i += 10
                continue
            if b0 == 0x02:                      # record `02 01 eY ZZ 00` (5 bytes)
                slots.append((reg[i + 2] << 8) | reg[i + 3])
                i += 5
                continue
            if b0 == 0x01:
                if reg[i + 1] == 0x01:          # record `01 01 eY ZZ 00` (5 bytes)
                    slots.append((reg[i + 2] << 8) | reg[i + 3])
                    i += 5
                    continue
                # name record: `01 <len> <name>\0`
                ln = reg[i + 1]
                nm = reg[i + 2:i + 2 + ln].decode("latin1")
                pins.append((nn, slots, nm))
                i += 2 + ln + 1
                continue
            if b0 in (0x0f, 0x0e, 0x12, 0x0c):
                b1, b2 = reg[i + 1], reg[i + 2]
                if b1 in (1, 2) and b2 == 0x01: # record `XX b1 01 eY ZZ 00` (6 bytes)
                    slots.append((reg[i + 3] << 8) | reg[i + 4])
                    i += 6
                    continue
                j = reg.find(b"\x00", i + 2)    # name, NUL-terminated
                if j < 0:
                    j = n
                nm = reg[i + 2:j].decode("latin1")
                pins.append((nn, slots, nm))
                i = j + 1
                continue
            if b0 in (0x04, 0x05):              # LSSD name, NUL-terminated from i+1
                j = reg.find(b"\x00", i + 1)
                if j < 0:
                    j = n
                nm = reg[i + 1:j].decode("latin1")
                pins.append((nn, slots, nm))
                i = j + 1
                continue
            i += 1
        # trailing group without a name (the last pin): append with empty name
        if slots:
            pins.append((nn, slots, ""))
        # map to pin.list by order (table order == pin.list order)
        result = {}
        if self.pinlist:
            for (nn, slots, nm), (pname, msb, lsb) in zip(pins, self.pinlist):
                result[pname] = [s for s in slots]
        else:
            for nn, slots, nm in pins:
                result[nm] = [s for s in slots]
        return result

    # ---- pin.list: (name, msb, lsb) ----
    def _pin_list(self, path):
        pl = []
        for line in open(path, encoding="latin1"):
            m = re.match(r"\s*ADD\s+(PIN_)?([A-Za-z0-9_]+)(?:\((\d+):(\d+)\))?", line)
            if m:
                name = m.group(2)
                msb = int(m.group(3)) if m.group(3) else 0
                lsb = int(m.group(4)) if m.group(4) else 0
                pl.append((name, msb, lsb))
        return pl


# ---------------------------------------------------------------------------
# 2. PowerPC interpreter (the subset used by the model)
# ---------------------------------------------------------------------------
# opcodes (kind) of the predecoded instructions
K_LBZ, K_LHZ, K_LHA, K_LWZ = 1, 2, 3, 4
K_STB, K_STH, K_STW = 5, 6, 7
K_ADD, K_ADDI, K_ADDIS, K_SUBFC, K_MULLI = 10, 11, 12, 13, 14
K_AND, K_ANDC, K_OR, K_ORC, K_NOR, K_NAND, K_XOR, K_EQV = 20, 21, 22, 23, 24, 25, 26, 27
K_ORI, K_ORIS, K_XORI, K_XORIS = 30, 31, 32, 33
K_CMPLWI, K_CMPLW = 40, 41
K_RLWINM, K_RLWIMI = 50, 51
K_B, K_BC = 60, 61
K_MTLR, K_MFLR, K_BLR, K_BLRL = 70, 71, 72, 73
K_STMW, K_LMW = 80, 81
K_NOP = 90
K_OTHER = 99

MNEM = {
    K_LBZ: "lbz", K_LHZ: "lhz", K_LHA: "lha", K_LWZ: "lwz",
    K_STB: "stb", K_STH: "sth", K_STW: "stw",
    K_ADD: "add", K_ADDI: "addi", K_ADDIS: "addis", K_SUBFC: "subfc", K_MULLI: "mulli",
    K_AND: "and", K_ANDC: "andc", K_OR: "or", K_ORC: "orc", K_NOR: "nor",
    K_NAND: "nand", K_XOR: "xor", K_EQV: "eqv",
    K_ORI: "ori", K_ORIS: "oris", K_XORI: "xori", K_XORIS: "xoris",
    K_CMPLWI: "cmplwi", K_CMPLW: "cmplw",
    K_RLWINM: "rlwinm", K_RLWIMI: "rlwimi",
    K_B: "b", K_BC: "bc", K_MTLR: "mtlr", K_MFLR: "mflr",
    K_BLR: "blr", K_BLRL: "blrl", K_STMW: "stmw", K_LMW: "lmw", K_NOP: "nop",
}

# kinds that read/write state memory (for --verbose)
LOAD_KINDS = (K_LBZ, K_LHZ, K_LHA, K_LWZ, K_LMW)
STORE_KINDS = (K_STB, K_STH, K_STW, K_STMW)


class CPU:
    def __init__(self, model):
        self.m = model
        self.mem = bytearray(STATE_SIZE)
        self.r = [0] * 32
        self.cr = [0] * 8          # 4 bits each: LT GT EQ SO
        self.lr = 0
        self.ctr = 0
        self.xer = 0
        self.pc = 0
        self.steps = 0
        self.max_steps = 0
        self.ret_marker = RETURN_MARKER
        self.trace = None
        # call block: function descriptors (the bootstrap copies them into
        # slots 0x4C..0x194)
        for off, (entry, toc) in FUNCDESC.items():
            p = 0x200 + off // 4 * 4
            self.mem[off:off + 4] = struct.pack(">I", p)      # pointer to descriptor
            self.mem[p:p + 12] = struct.pack(">III", entry, toc, 0)
        self.mem[0x10:0x14] = struct.pack(">I", 0)            # model base = 0 (slot 0x8010)
        self.mem[0x40:0x44] = struct.pack(">I", 0)            # slot 0x8040: assert msg offset
        self.mem[0x44:0x48] = struct.pack(">I", 0)            # slot 0x8044
        # assert statistics
        self.assert_count = 0
        self.assert_seen = set()
        self.maxasserts = 3
        self.assert_log = []
        self.faults = []
        # verbose cell-name logging
        self.verbose = False
        self.verbose_max = 0
        self.verbose_count = 0
        self.verbose_overflow = False
        # predecode the code
        self._predecode()

    def _blr_debug(self, at, tgt):
        print("  [blr] bad return @0x%x -> 0x%x" % (at, tgt))
        print("        r10=0x%x lr=0x%x r13=0x%x r1=0x%x r25=0x%x"
              % (self.r[10], self.lr, self.r[13], self.r[1], self.r[25]))
        print("        last steps:", " ".join("0x%x" % a for a in self.tail[-20:]))

    def _memfault(self, at, addr):
        if len(self.faults) < 32:
            self.faults.append((at, addr))

    def _hot_report(self, start, max_steps):
        """Prints frequent execution addresses (hang diagnostics)."""
        if not self.debug:
            return
        from collections import Counter
        c = Counter(self.hot)
        print("  [hot] top-10 addresses (sample):")
        for a, cnt in c.most_common(10):
            print("    0x%x: %d" % (a, cnt))
        seq = sorted(self.hot)
        print("  [hot] sampled addresses in order (head):")
        for a in seq[:24]:
            print("    0x%x" % a)
        print("  [tail] last 64 addresses:")
        for a in self.tail:
            print("    0x%x" % a)
        print("  [wraps] backward jumps (step, from, to):")
        for s, f, t in self.wraps[:12]:
            print("    step %d: 0x%x -> 0x%x" % (s, f, t))

    # ---------------- predecode ----------------
    def _predecode(self):
        d = self.m.code
        self.ins = []
        self.addr_idx = {}
        start = 0x0
        end = CODE_END
        for a in range(start, end, 4):
            w = struct.unpack(">I", d[a:a + 4])[0]
            self.ins.append(self._decode(a, w))
        for i, ins in enumerate(self.ins):
            self.addr_idx[ins[0]] = i

    def _decode(self, a, w):
        op = w >> 26
        rt = (w >> 21) & 0x1F
        ra = (w >> 16) & 0x1F
        rb = (w >> 11) & 0x1F
        d16 = w & 0xFFFF
        sd = d16 - 0x10000 if d16 & 0x8000 else d16
        if op == 14:     # addi / li
            return (a, K_ADDI, rt, ra, sd)
        if op == 15:     # addis / lis
            return (a, K_ADDIS, rt, ra, sd)
        if op == 10:     # cmplwi
            return (a, K_CMPLWI, ra, d16)
        if op == 24:     # ori
            return (a, K_ORI, rt, ra, d16)
        if op == 25:     # oris
            return (a, K_ORIS, rt, ra, d16)
        if op == 26:     # xori
            return (a, K_XORI, rt, ra, d16)
        if op == 27:     # xoris
            return (a, K_XORIS, rt, ra, d16)
        if op == 7:      # mulli
            return (a, K_MULLI, rt, ra, sd)
        if op == 20:     # rlwimi
            return (a, K_RLWIMI, rt, ra, (w >> 11) & 0x1F, (w >> 6) & 0x1F, (w >> 1) & 0x1F)
        if op == 21:     # rlwinm
            return (a, K_RLWINM, rt, ra, (w >> 11) & 0x1F, (w >> 6) & 0x1F, (w >> 1) & 0x1F)
        if op == 32:     # lwz
            return (a, K_LWZ, rt, ra, sd)
        if op == 34:     # lbz
            return (a, K_LBZ, rt, ra, sd)
        if op == 40:     # lhz
            return (a, K_LHZ, rt, ra, sd)
        if op == 42:     # lha
            return (a, K_LHA, rt, ra, sd)
        if op == 36:     # stw
            return (a, K_STW, rt, ra, sd)
        if op == 38:     # stb
            return (a, K_STB, rt, ra, sd)
        if op == 44:     # sth
            return (a, K_STH, rt, ra, sd)
        if op == 46:     # lmw
            return (a, K_LMW, rt, ra, sd)
        if op == 47:     # stmw
            return (a, K_STMW, rt, ra, sd)
        if op == 18:     # b / bl
            lk = w & 1
            aa = (w >> 1) & 1
            li = (w >> 2) & 0xFFFFFF
            if li & 0x800000:
                li -= 0x1000000
            tgt = (li << 2) if aa else (a + (li << 2))
            if lk:
                return (a, K_OTHER, "bl", tgt)
            return (a, K_B, tgt)
        if op == 16:     # bc (beq/bne/...)
            bo = (w >> 21) & 0x1F
            bi = (w >> 16) & 0x1F
            bd = (w >> 2) & 0x3FFF
            if bd & 0x2000:
                bd -= 0x4000
            aa = (w >> 1) & 1
            lk = w & 1
            tgt = (bd << 2) if aa else (a + (bd << 2))
            return (a, K_BC, bo, bi, tgt, lk)
        if op == 19:     # special: blr / blrl
            if w == 0x4E800020:
                return (a, K_BLR)
            if w == 0x4E800021:
                return (a, K_BLRL)
            return (a, K_OTHER, "op19", w)
        if op == 31:
            xo = (w >> 1) & 0x3FF
            rc = w & 1
            if xo == 28:      # and
                return (a, K_AND, rt, ra, rb, rc)
            if xo == 60:      # andc
                return (a, K_ANDC, rt, ra, rb, rc)
            if xo == 444:     # or
                return (a, K_OR, rt, ra, rb, rc)
            if xo == 412:     # orc
                return (a, K_ORC, rt, ra, rb, rc)
            if xo == 124:     # nor
                return (a, K_NOR, rt, ra, rb, rc)
            if xo == 476:     # nand
                return (a, K_NAND, rt, ra, rb, rc)
            if xo == 316:     # xor
                return (a, K_XOR, rt, ra, rb, rc)
            if xo == 284:     # eqv
                return (a, K_EQV, rt, ra, rb, rc)
            if xo == 266:     # add
                return (a, K_ADD, rt, ra, rb, rc)
            if xo == 8:       # subfc
                return (a, K_SUBFC, rt, ra, rb, rc)
            if xo == 32:      # cmplw
                return (a, K_CMPLW, ra, rb)
            if xo == 339:     # mflr
                return (a, K_MFLR, rt)
            if xo == 467:     # mtlr
                return (a, K_MTLR, rt)
            if xo == 18:      # blr
                return (a, K_BLR)
            if xo == 275:     # blrl
                return (a, K_BLRL)
            return (a, K_OTHER, "op31/xo%d" % xo, w)
        if w == 0x60000000:
            return (a, K_NOP)
        return (a, K_OTHER, "op%d" % op, w)

    # ---------------- basic operations ----------------
    def _cr_set(self, f, lt, gt, eq):
        self.cr[f] = (1 if lt else 0) | (2 if gt else 0) | (4 if eq else 0)

    def _cr_bit(self, bi):
        return (self.cr[bi >> 2] >> (bi & 3)) & 1

    @staticmethod
    def _rotl(v, sh):
        return ((v << sh) | (v >> (32 - sh))) & 0xFFFFFFFF if sh else v

    @staticmethod
    def _mask(mb, me):
        if mb <= me:
            return ((0xFFFFFFFF << (31 - me)) & (0xFFFFFFFF >> mb)) & 0xFFFFFFFF
        return (0xFFFFFFFF << (32 - mb)) | (0xFFFFFFFF >> (me + 1))

    # ---------------- assert printer (MVLSIM stub) ----------------
    def _assert_print(self, pc):
        off = struct.unpack(">I", self.mem[0x40:0x44])[0]
        if off == 0 or off in self.assert_seen:
            return
        rec = self.m.assert_at(off)
        self.assert_seen.add(off)
        self.assert_count += 1
        if rec:
            sev, path, text = rec
            line = "%d | %s >  %s" % (sev, path, text)
        else:
            line = "(offset 0x%x)" % off
        self.assert_log.append((off, line))
        if len(self.assert_log) <= self.maxasserts:
            print("  ASSERT #%d: %s" % (self.assert_count, line), flush=True)

    # ---------------- verbose cell access logging ----------------
    def _vlog(self, ins, is_store, value=None):
        """--verbose: print the name of a known cell on load/store access."""
        if not self.verbose:
            return
        if self.verbose_max and self.verbose_count >= self.verbose_max:
            if not self.verbose_overflow:
                self.verbose_overflow = True
                print("  ... (verbose output capped at %d accesses per pass)"
                      % self.verbose_max, flush=True)
            return
        ra = ins[3]
        if ra < 13 or ra > 20:
            return                       # non-bank base (call block / heap) — no slot name
        d = ins[4]
        slot = d if d >= 0 else d + 0x10000
        name = self.m.slot_name(slot)
        if not name:
            return
        self.verbose_count += 1
        kind = "Store" if is_store else "Load"
        vtxt = ("= %d" % value) if value is not None else ""
        print("  %s @0x%06x %-4s %s (slot 0x%04x) %s"
              % (kind, ins[0], MNEM.get(ins[1], "?"), name, slot, vtxt), flush=True)

    # ---------------- execution loop ----------------
    def run(self, start, end_addr=None, max_steps=0, trace=None):
        """Executes code from start until RETURN_MARKER / end of code."""
        idx = self.addr_idx.get(start)
        if idx is None:
            raise ValueError("no code at address 0x%x" % start)
        # restart registers (as on a call from MVLSIM: r3 = call block, r1 = stack)
        for k in range(32):
            self.r[k] = 0
        self.r[3] = CALLBLK
        self.r[1] = 0x7FFC
        for k in range(8):
            self.cr[k] = 0
        self.ctr = 0
        self.xer = 0
        self.lr = self.ret_marker
        self.steps = 0
        self.hot = {}
        self.tail = []
        self.wraps = []
        self.debug = False
        self.verbose_count = 0
        self.verbose_overflow = False
        self.prev_pc = start
        ins_list = self.ins
        r = self.r
        cr = self.cr
        mem = self.mem
        n = len(ins_list)
        end_idx = self.addr_idx.get(end_addr, n) if end_addr else n
        i = idx
        while 0 <= i < end_idx:
            self.steps += 1
            if max_steps and self.steps > max_steps:
                self._hot_report(start, max_steps)
                return "max_steps"
            ins = ins_list[i]
            if (self.steps & 0xFFF) == 0:
                self.hot[ins[0]] = self.hot.get(ins[0], 0) + 1
            self.tail.append(ins[0])
            if len(self.tail) > 64:
                self.tail.pop(0)
            if ins[0] < self.prev_pc - 0x10000 and len(self.wraps) < 40:
                self.wraps.append((self.steps, self.prev_pc, ins[0]))
            self.prev_pc = ins[0]
            if self.trace and self.steps <= self.trace:
                print("%6d 0x%06x %s r13=0x%x lr=0x%x"
                      % (self.steps, ins[0], MNEM.get(ins[1], "??"), self.r[13], self.lr), flush=True)
            k = ins[1]
            if k == K_ADDI:
                v = (r[ins[3]] if ins[3] else 0) + ins[4]
                r[ins[2]] = v & 0xFFFFFFFF
            elif k == K_ADDIS:
                v = (r[ins[3]] if ins[3] else 0) + ((ins[4] << 16) & 0xFFFFFFFF)
                r[ins[2]] = v & 0xFFFFFFFF
            elif k == K_CMPLWI:
                a = r[ins[2]]
                b = ins[3]
                self._cr_set(0, a < b, a > b, a == b)
            elif k == K_CMPLW:
                a = r[ins[2]]
                b = r[ins[3]]
                self._cr_set(0, a < b, a > b, a == b)
            elif k == K_ORI:
                r[ins[2]] = (r[ins[3]] | ins[4]) & 0xFFFFFFFF
            elif k == K_ORIS:
                r[ins[2]] = (r[ins[3]] | (ins[4] << 16)) & 0xFFFFFFFF
            elif k == K_XORI:
                r[ins[2]] = (r[ins[3]] ^ ins[4]) & 0xFFFFFFFF
            elif k == K_XORIS:
                r[ins[2]] = (r[ins[3]] ^ (ins[4] << 16)) & 0xFFFFFFFF
            elif k == K_MULLI:
                r[ins[2]] = (r[ins[3]] * ins[4]) & 0xFFFFFFFF
            elif k == K_RLWINM:
                rs = r[ins[3]]
                v = self._rotl(rs, ins[4]) & self._mask(ins[5], ins[6])
                r[ins[2]] = v
            elif k == K_RLWIMI:
                rs = r[ins[3]]
                m = self._mask(ins[5], ins[6])
                v = (self._rotl(rs, ins[4]) & m) | (r[ins[2]] & ~m)
                r[ins[2]] = v & 0xFFFFFFFF
            elif k == K_AND:
                v = r[ins[3]] & r[ins[4]]
                r[ins[2]] = v
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_ANDC:
                v = r[ins[3]] & ~r[ins[4]]
                r[ins[2]] = v & 0xFFFFFFFF
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_OR:
                v = r[ins[3]] | r[ins[4]]
                r[ins[2]] = v
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_ORC:
                v = r[ins[3]] | ~r[ins[4]]
                r[ins[2]] = v & 0xFFFFFFFF
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_NOR:
                v = ~(r[ins[3]] | r[ins[4]])
                r[ins[2]] = v & 0xFFFFFFFF
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_NAND:
                v = ~(r[ins[3]] & r[ins[4]])
                r[ins[2]] = v & 0xFFFFFFFF
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_XOR:
                v = r[ins[3]] ^ r[ins[4]]
                r[ins[2]] = v
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_EQV:
                v = ~(r[ins[3]] ^ r[ins[4]])
                r[ins[2]] = v & 0xFFFFFFFF
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_ADD:
                v = (r[ins[3]] + r[ins[4]]) & 0xFFFFFFFF
                r[ins[2]] = v
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_SUBFC:
                v = (r[ins[4]] - r[ins[3]]) & 0xFFFFFFFF
                r[ins[2]] = v
                if ins[5]:
                    self._cr_set(0, (v >> 31) & 1, v != 0 and not (v >> 31), v == 0)
            elif k == K_LBZ:
                a = r[ins[3]] + ins[4]
                if 0 <= a < len(mem):
                    v = mem[a]
                    r[ins[2]] = v
                    self._vlog(ins, False, v)
                else:
                    self._memfault(ins[0], a)
                    r[ins[2]] = 0
            elif k == K_LHZ:
                a = r[ins[3]] + ins[4]
                if 0 <= a < len(mem) - 1:
                    v = (mem[a] << 8) | mem[a + 1]
                    r[ins[2]] = v
                    self._vlog(ins, False, v)
                else:
                    self._memfault(ins[0], a)
                    r[ins[2]] = 0
            elif k == K_LHA:
                a = r[ins[3]] + ins[4]
                if 0 <= a < len(mem) - 1:
                    v = (mem[a] << 8) | mem[a + 1]
                    if v & 0x8000:
                        v -= 0x10000
                    r[ins[2]] = v
                    self._vlog(ins, False, v & 0xFFFF)
                else:
                    self._memfault(ins[0], a)
                    r[ins[2]] = 0
            elif k == K_LWZ:
                a = r[ins[3]] + ins[4]
                if 0 <= a < len(mem) - 3:
                    v = (mem[a] << 24) | (mem[a + 1] << 16) | (mem[a + 2] << 8) | mem[a + 3]
                    r[ins[2]] = v
                    self._vlog(ins, False, v)
                else:
                    self._memfault(ins[0], a)
                    r[ins[2]] = 0
            elif k == K_STB:
                a = r[ins[3]] + ins[4]
                if 0 <= a < len(mem):
                    mem[a] = r[ins[2]] & 0xFF
                    self._vlog(ins, True, r[ins[2]] & 0xFF)
                else:
                    self._memfault(ins[0], a)
            elif k == K_STH:
                a = r[ins[3]] + ins[4]
                if 0 <= a < len(mem) - 1:
                    v = r[ins[2]] & 0xFFFF
                    mem[a] = v >> 8
                    mem[a + 1] = v & 0xFF
                    self._vlog(ins, True, v)
                else:
                    self._memfault(ins[0], a)
            elif k == K_STW:
                a = r[ins[3]] + ins[4]
                if 0 <= a < len(mem) - 3:
                    v = r[ins[2]] & 0xFFFFFFFF
                    mem[a] = v >> 24
                    mem[a + 1] = (v >> 16) & 0xFF
                    mem[a + 2] = (v >> 8) & 0xFF
                    mem[a + 3] = v & 0xFF
                    self._vlog(ins, True, v)
                else:
                    self._memfault(ins[0], a)
            elif k == K_STMW:
                a = r[ins[3]] + ins[4]
                self._vlog(ins, True, r[ins[2]] & 0xFFFFFFFF)
                for rr in range(ins[2], 32):
                    if 0 <= a < len(mem) - 3:
                        v = r[rr] & 0xFFFFFFFF
                        mem[a] = v >> 24
                        mem[a + 1] = (v >> 16) & 0xFF
                        mem[a + 2] = (v >> 8) & 0xFF
                        mem[a + 3] = v & 0xFF
                    else:
                        self._memfault(ins[0], a)
                    a += 4
            elif k == K_LMW:
                a = r[ins[3]] + ins[4]
                self._vlog(ins, False, None)
                for rr in range(ins[2], 32):
                    if 0 <= a < len(mem) - 3:
                        r[rr] = (mem[a] << 24) | (mem[a + 1] << 16) | (mem[a + 2] << 8) | mem[a + 3]
                    else:
                        self._memfault(ins[0], a)
                        r[rr] = 0
                    a += 4
            elif k == K_B:
                i = self.addr_idx.get(ins[2])
                if i is None:
                    return "branch out of code -> 0x%x" % ins[2]
                continue
            elif k == K_BC:
                bo, bi, tgt = ins[2], ins[3], ins[4]
                # PPC BO field: the model only emits BO=12 (beq) and BO=4 (bne).
                #   BO=12 (0b01100): branch if CR[BI] == 1  (beq/blt/bgt/bso)
                #   BO=4  (0b00100): branch if CR[BI] == 0  (bne/bge/ble/bns)
                # (the CR-test polarity is bit3 of BO, not bit2)
                if bo == 12:
                    take = self._cr_bit(bi) == 1
                else:
                    take = self._cr_bit(bi) == 0
                if take:
                    i = self.addr_idx.get(tgt)
                    if i is None:
                        return "bc out of code -> 0x%x" % tgt
                    continue
            elif k == K_MTLR:
                self.lr = r[ins[2]]
            elif k == K_MFLR:
                r[ins[2]] = self.lr
            elif k == K_BLR:
                t = self.lr
                if t == self.ret_marker or t not in self.addr_idx:
                    if t != self.ret_marker:
                        self._blr_debug(ins[0], t)
                    return "done"
                if t < 0x100000 and len(self.wraps) < 40:
                    self.wraps.append((self.steps, ins[0], t))
                    self._blr_debug(ins[0], t)
                i = self.addr_idx[t]
                continue
            elif k == K_BLRL:
                t = self.lr
                self.lr = ins[0] + 4
                if t == ASSERT_PRINTER:
                    self._assert_print(ins[0])
                    i += 1
                    continue
                if t not in self.addr_idx:
                    # external MVLSIM function: return stub
                    i += 1
                    continue
                i = self.addr_idx[t]
                continue
            elif k == K_NOP:
                pass
            else:
                return "unsupported @0x%x: %r" % (ins[0], ins[2:])
            i += 1
        return "end_of_range"

    # ---------------- pins ----------------
    def _slot_addr(self, slot, bank=2):
        """Address of a slot in a bank: slot>=0x8000 -> negative displacement."""
        d = slot - 0x10000 if slot >= 0x8000 else slot
        base = 0x8000 + bank * 0x10000
        return base + d

    def pin_slots(self, pin_name):
        """Slots of a pin from the table; pin.list names without the PIN_ prefix."""
        p = self.m.pins.get(pin_name)
        if p is not None:
            return p
        return self.m.pins.get("PIN_" + pin_name)

    def set_pin(self, pin_name, value, bits=None):
        """Applies a pin value to all banks (L1/L2 copies).
        Each bit has 2 table slots (pairs); both are written."""
        slots = self.pin_slots(pin_name)
        if not slots:
            return False
        if isinstance(value, str):
            if value.lower().startswith("0x"):
                value = int(value, 16)
            else:
                value = int(value, 0)
        nb = bits if bits and bits > 0 else len(slots)
        per = max(1, len(slots) // nb)
        for bi in range(min(nb, len(slots))):
            bit = (value >> (nb - 1 - bi)) & 1
            for s in slots[bi * per:(bi + 1) * per]:
                for bank in range(8):
                    self.mem[self._slot_addr(s, bank)] = bit
        return True

    def get_pin(self, pin_name, bits=None, bank=2):
        """Reads a pin from a bank (default 2 — the r15 plane).
        Returns the value from the first slot of each pair (per bit)."""
        slots = self.pin_slots(pin_name)
        if not slots:
            return None
        nb = bits if bits and bits > 0 else len(slots)
        per = max(1, len(slots) // nb)
        v = 0
        for bi in range(min(nb, len(slots))):
            s = slots[bi * per]
            v = (v << 1) | self.mem[self._slot_addr(s, bank)]
        return v


# ---------------------------------------------------------------------------
# 3. Input map
# ---------------------------------------------------------------------------
def gen_input_template(path, cycles):
    """Generates an input map template: reset (4 cycles) + idle cycles."""
    lines = []
    lines.append("# cosim.py input map template (reset + %d idle cycles)" % cycles)
    lines.append("# Format: <cycle>[:<end>] <PIN>=<value> ...  ('-' = keep, '*' = repeat)")
    lines.append("# Pins start at 0; active-low: X_=0 means 'asserted'.")
    reset = ("SYSCLK=0 HRESET_=0 SRESET_=0 A=0x00000000 DH=0x00000000 DL=0x00000000 "
             "TS_=0 TT=0x00 TSIZ=0x0 CI_=0 WT_=1 GBL_=1 AP=0x0 DP=0x00 ARTRY_=1 BR_=0 "
             "BG_=1 QREQ_=0 DRTRY_=1 TEA_=1 TLBISYNC_=1 MCP_=1 INT_=1 CKSTP_=1 "
             "CHECKSTOP_=1 LSSD_MODE_=1 TRST_=1 TMS=0 TCK=0 TDI=0 L1_TSTCLK=0 L2_TSTCLK=0")
    lines.append("0 " + reset)
    lines.append("1 SYSCLK=1")
    lines.append("2 SYSCLK=0")
    lines.append("3 SYSCLK=1")
    lines.append("# --- reset deasserted ---")
    lines.append("4 SYSCLK=0 HRESET_=1 SRESET_=1")
    lines.append("5 SYSCLK=1")
    for c in range(6, cycles):
        lines.append("%d SYSCLK=%d" % (c, 0 if c % 2 == 0 else 1))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("cosim: input template written: %s (%d cycles)" % (path, cycles))


def parse_inputs(path):
    """Lines '<cyc>[:<cyc2>] PIN=val ...'; '*' repeats the previous line."""
    plan = {}          # cycle -> {pin: value}
    order = []         # pin order for the log
    last = None
    cyc = 0
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "*":
            cyc += 1
            if last is not None:
                plan[cyc] = dict(last)
            continue
        m = re.match(r"^(\d+)(?::(\d+))?\s+(.*)$", line)
        if not m:
            raise ValueError("input line not parsed: %r" % line)
        c1 = int(m.group(1))
        c2 = int(m.group(2)) if m.group(2) else c1
        body = m.group(3)
        vals = {}
        for tok in body.split():
            if "=" not in tok:
                raise ValueError("token without '=': %r" % tok)
            k, v = tok.split("=", 1)
            if v == "-":
                continue
            vals[k] = v
            if k not in order:
                order.append(k)
        for c in range(c1, c2 + 1):
            plan[c] = dict(vals)
        cyc = c2
        last = vals
    return plan, order


# ---------------------------------------------------------------------------
# 4. main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="MVLSIM model interpreter (GKO)")
    ap.add_argument("-m", "--model", default="model/COSIM.m2630opt.Jul1599")
    ap.add_argument("-p", "--pinlist", default="model/pin.list")
    ap.add_argument("-i", "--inputs", help="per-cycle input signal map (txt)")
    ap.add_argument("-n", "--cycles", type=int, default=100)
    ap.add_argument("-o", "--log", help="log file")
    ap.add_argument("-d", "--dump", help="per-cycle dump of all signals")
    ap.add_argument("--maxasserts", type=int, default=3)
    ap.add_argument("--no-init", action="store_true",
                    help="skip the one-time init pass (bootstrap #1, 0x2C)")
    ap.add_argument("--maxsteps", type=int, default=0,
                    help="instruction cap per pass (0 = auto)")
    ap.add_argument("--trace", type=int, default=0, metavar="N",
                    help="print the first N instructions of each pass")
    ap.add_argument("--verbose", action="store_true",
                    help="print known cell names on every load/store to a "
                         "state-bank slot, marked Load/Store")
    ap.add_argument("--verbose-max", type=int, default=0, metavar="N",
                    help="cap verbose accesses printed per pass (0 = unlimited)")
    ap.add_argument("--debug", action="store_true",
                    help="interpreter diagnostics (hot addresses, wraps)")
    ap.add_argument("--gen-input", metavar="FILE", default=None,
                    help="write an input map template (reset + N cycles) and exit")
    ap.add_argument("--dump-changed-only", action="store_true",
                    help="dump only the slots changed that cycle")
    args = ap.parse_args()

    if args.gen_input:
        gen_input_template(args.gen_input, args.cycles)
        return

    t0 = time.time()
    print("cosim: reading model %s ..." % args.model, flush=True)
    m = Model(args.model, args.pinlist)
    print("cosim: header: date %s, version %d, flags 0x%02x, patch nodes %d"
          % (m.build_date, m.hdr.get(0x14), m.flags, m.patch_count))
    print("cosim: per-cycle entry 0x%x, named slots %d, messages %d, pins %d"
          % (m.entry, len(m.slot_names), len(m.messages), len(m.pins)))

    cpu = CPU(m)
    cpu.maxasserts = args.maxasserts
    cpu.trace = args.trace
    cpu.debug = args.debug
    cpu.verbose = args.verbose
    cpu.verbose_max = args.verbose_max

    # ---- bootstrap #1: load-time initialization ----
    if not args.no_init:
        print("cosim: init pass (0x%x) ..." % ENTRY_INIT, flush=True)
        r = cpu.run(ENTRY_INIT, max_steps=args.maxsteps or 2000000)
        print("cosim: init done: %s, steps %d" % (r, cpu.steps))
    # ---- input map ----
    plan = {}
    order = []
    if args.inputs:
        plan, order = parse_inputs(args.inputs)
        print("cosim: input map: %d cycles, %d pins" % (len(plan), len(order)))

    logf = open(args.log, "w", encoding="utf-8") if args.log else None
    dumpf = open(args.dump, "w", encoding="utf-8") if args.dump else None

    def log(s=""):
        if logf:
            logf.write(s + "\n")
        print(s, flush=True)

    def dump(s=""):
        if dumpf:
            dumpf.write(s + "\n")

    log("MVLSIM-like simulation of %s (interpreter cosim.py)" % m.path)
    log("Cycles: %d, entry 0x%x, asserts printed: first %d" % (args.cycles, m.entry, args.maxasserts))

    # pin widths and values (for the input log)
    pinvals = {}       # pin -> last applied value
    pinwidth = {}
    for nm, msb, lsb in (m.pinlist or []):
        w = abs(msb - lsb) + 1
        pinwidth[nm] = w
        pinvals.setdefault(nm, 0)

    # which pins the input map drives (the rest are monitored outputs)
    input_pins = set()
    for c, vals in plan.items():
        input_pins.update(vals.keys())

    eval_steps = 0
    total_asserts = 0
    prev_state = None
    for cyc in range(args.cycles):
        # apply inputs
        applied = []
        if cyc in plan:
            for pn, v in plan[cyc].items():
                if cpu.set_pin(pn, v, pinwidth.get(pn)):
                    try:
                        pinvals[pn] = int(v, 0)
                    except Exception:
                        pass
                    applied.append("%s=%s" % (pn, v))
                else:
                    log("WARN: pin '%s' not found in the pin table" % pn)
        # one model pass: entry #2 (fast path) + entry #3 (full netlist)
        cpu.assert_seen = set()
        cpu.assert_log = []
        r = cpu.run(m.entry, max_steps=args.maxsteps or 10000000)
        eval_steps += cpu.steps
        total_asserts += cpu.assert_count
        if r != "done" and r != "end_of_range":
            log("CYCLE %d: model ended abnormally: %s (%d steps)" % (cyc, r, cpu.steps))
        if cpu.faults:
            log("  mem-faults: %d (first: %s)"
                % (len(cpu.faults), ", ".join("0x%x@0x%x" % (f[1] & 0xFFFFFFFF, f[0]) for f in cpu.faults[:4])))
            cpu.faults = []
        cpu.assert_log = []
        r3 = cpu.run(ENTRY_STAGE3, max_steps=args.maxsteps or 100000000)
        eval_steps += cpu.steps
        total_asserts += cpu.assert_count
        if r3 != "done" and r3 != "end_of_range":
            log("CYCLE %d: model stage3 ended abnormally: %s (%d steps)" % (cyc, r3, cpu.steps))
        if cpu.faults:
            log("  mem-faults: %d (first: %s)"
                % (len(cpu.faults), ", ".join("0x%x@0x%x" % (f[1] & 0xFFFFFFFF, f[0]) for f in cpu.faults[:4])))
            cpu.faults = []

        # ---- per-cycle log ----
        log("== cycle %d ==" % cyc)
        if applied:
            log("  inputs: " + " ".join(applied))
        if cpu.assert_log:
            for off, line in cpu.assert_log:
                log("  ASSERT #%d: " % total_asserts + line)
        # output pins (monitoring)
        outs = []
        for nm, msb, lsb in (m.pinlist or []):
            if nm in input_pins:
                continue
            w = pinwidth.get(nm, 1)
            v = cpu.get_pin(nm, w)
            if v is not None:
                outs.append("%s=%s" % (nm, hex(v) if w > 1 else v))
        if outs:
            log("  outputs: " + " ".join(outs))
        # named signals (changes)
        changed = []
        for slot, name in m.slot_names.items():
            a2 = cpu._slot_addr(slot, 2)
            a0 = cpu._slot_addr(slot, 0)
            v = cpu.mem[a2]
            if prev_state is not None and (prev_state[a2] != v or prev_state[a0] != cpu.mem[a0]):
                changed.append((slot, name, prev_state[a2], v))
        if changed:
            log("  changed named: %d (examples: %s)"
                % (len(changed), ", ".join("%s=%d" % (nm, v) for _, nm, _, v in changed[:8])))
        if dumpf:
            dump("== cycle %d ==" % cyc)
            dump("  inputs: " + " ".join(applied))
            dump("  outputs: " + " ".join(outs))
            if args.dump_changed_only:
                cur = bytes(cpu.mem)
                if prev_state is not None:
                    for slot, name in m.slot_names.items():
                        a2 = cpu._slot_addr(slot, 2)
                        a0 = cpu._slot_addr(slot, 0)
                        if cur[a2] != prev_state[a2] or cur[a0] != prev_state[a0]:
                            dump("  %-4s %s = %d" % (hex(slot), name, cur[a2]))
            else:
                for slot, name in sorted(m.slot_names.items()):
                    a2 = cpu._slot_addr(slot, 2)
                    dump("  %-4s %s = %d" % (hex(slot), name, cpu.mem[a2]))
            dump("")
        prev_state = bytes(cpu.mem)

    dt = time.time() - t0
    log("== summary ==")
    log("cycles: %d, model instructions executed: %d, asserts: %d" % (args.cycles, eval_steps, total_asserts))
    log("elapsed: %.2f s (%.2f s/cycle)" % (dt, dt / max(1, args.cycles)))

    if logf:
        logf.close()
    if dumpf:
        dumpf.close()


if __name__ == "__main__":
    main()
