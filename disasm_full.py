#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
disasm_full.py -- full annotated disassembly of the compiled GKO model.

The model is a flat PowerPC program (compiled netlist).  This tool decodes
every 4-byte word of the code region [0x0, 0x4BA840) using the exact same
decoder as cosim.py (so all spec findings are honoured automatically):

  * the patch-list nodes (38,738 links at scattered addresses, head
    0x4BA800) are NOP'd (0x60000000) before decoding, exactly as MVLSIM
    patches 'ppc'-type models — they decode as `nop` and are marked
    `[patch]`;
  * slots are bank offsets: displacement >= 0 -> slot = disp, disp < 0 ->
    slot = disp + 0x10000; loads/stores through the bank pointers
    r13..r20 are annotated with the resolved slot and its signal name;
  * the L1/L2 copies are separate slots (both shown by name);
  * per-cycle structure markers (entry points, early returns) are added.

Output format (one instruction per line):
  0xADDR  MNEMONIC  OPERANDS   // [patch] | slot 0xXXXX GKO.<block>... | <note>

Usage:  python3 disasm_full.py
Output: model/COSIM.m2630opt.Jul1599.disasm.txt
"""
import importlib.util
import struct
import time

spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
cosim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cosim)

MODEL = "model/COSIM.m2630opt.Jul1599"
OUT = "model/COSIM.m2630opt.Jul1599.disasm.txt"

# (addr, label) markers
MARKERS = [
    (0x2C, "== bootstrap #1: init pass =="),
    (0x1BCD60, "== bootstrap #2: per-cycle entry (fast path) =="),
    (0x1DE3A4, "== idle early return (mtlr r10; blr) =="),
    (0x2341C8, "== per-cycle #2 return (mtlr r10; blr) =="),
    (0x2341CC, "== bootstrap #3: per-cycle full netlist =="),
    (0x4BA83C, "== final return (mtlr r10; blr) =="),
    (0x4BA800, "== patch list head (data) =="),
    (0x1210C8, "== dispatch table (data) =="),
]
MARKER_DICT = dict(MARKERS)

BANK_REGS = {13: 0, 14: 1, 15: 2, 16: 3, 17: 4, 18: 5, 19: 6, 20: 7}


def fmt_ins(m, i):
    """Format one decoded instruction tuple into (text, annotation)."""
    a, k = i[0], i[1]
    ann = []
    if k in (cosim.K_LBZ, cosim.K_LHZ, cosim.K_LHA, cosim.K_LWZ, cosim.K_LMW,
             cosim.K_STB, cosim.K_STH, cosim.K_STW, cosim.K_STMW):
        rt, ra, sd = i[2], i[3], i[4]
        mn = cosim.MNEM[k]
        if k in (cosim.K_LMW, cosim.K_STMW):
            text = "%s r%d, %d(r%d)" % (mn, rt, sd, ra)
        else:
            text = "%s r%d, %d(r%d)" % (mn, rt, sd, ra)
        if ra in BANK_REGS:
            slot = sd & 0xFFFF
            name = m.slot_names.get(slot, "")
            ann.append("slot 0x%04x %s" % (slot, name if name else ""))
        return text, " ".join(ann)
    if k == cosim.K_ADDI:
        return "addi r%d, r%d, %d" % (i[2], i[3], i[4]), ""
    if k == cosim.K_ADDIS:
        return "addis r%d, r%d, %d" % (i[2], i[3], i[4]), ""
    if k == cosim.K_CMPLWI:
        return "cmplwi r%d, %d" % (i[2], i[3]), ""
    if k == cosim.K_CMPLW:
        return "cmplw r%d, r%d" % (i[2], i[3]), ""
    if k in (cosim.K_ORI, cosim.K_ORIS, cosim.K_XORI, cosim.K_XORIS):
        return "%s r%d, r%d, 0x%x" % (cosim.MNEM[k], i[2], i[3], i[4]), ""
    if k == cosim.K_MULLI:
        return "mulli r%d, r%d, %d" % (i[2], i[3], i[4]), ""
    if k == cosim.K_RLWIMI:
        return "rlwimi r%d, r%d, %d, %d, %d" % (i[2], i[3], i[4], i[5], i[6]), ""
    if k == cosim.K_RLWINM:
        return "rlwinm r%d, r%d, %d, %d, %d" % (i[2], i[3], i[4], i[5], i[6]), ""
    if k in (cosim.K_AND, cosim.K_ANDC, cosim.K_OR, cosim.K_ORC, cosim.K_NOR,
             cosim.K_NAND, cosim.K_XOR, cosim.K_EQV, cosim.K_ADD,
             cosim.K_SUBFC):
        rc = " ." if (len(i) > 5 and i[5]) else ""
        return "%s r%d, r%d, r%d%s" % (cosim.MNEM[k], i[2], i[3], i[4], rc), ""
    if k == cosim.K_B:
        return "b 0x%x" % i[2], ""
    if k == cosim.K_BC:
        bo, bi, tgt = i[2], i[3], i[4]
        hint = "beq" if bo == 12 else ("bne" if bo == 4 else "bc(bo=%d)" % bo)
        return "%s %d -> 0x%x" % (hint, bi, tgt), ""
    if k == cosim.K_MTLR:
        return "mtlr r%d" % i[2], ""
    if k == cosim.K_MFLR:
        return "mflr r%d" % i[2], ""
    if k == cosim.K_BLR:
        return "blr", ""
    if k == cosim.K_BLRL:
        return "blrl", ""
    if k == cosim.K_NOP:
        return "nop", "[patch]"
    if k == cosim.K_OTHER:
        return "%s" % (i[2] if len(i) > 2 else "?"), ""
    return "?", ""


def main():
    m = cosim.Model(MODEL, "model/pin.list")
    cpu = cosim.CPU(m)
    print("predecoded %d instructions" % len(cpu.ins))

    t0 = time.time()
    buf = []
    B = 4096  # flush buffer size in lines
    n = 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# Full annotated disassembly of %s\n" % MODEL)
        f.write("# decoder: cosim.py (patch nodes NOP'd, slots = bank "
                "offsets, disp<0 -> slot+0x10000)\n")
        f.write("# region markers: init 0x2C..0x1BCD60 | per-cycle #2 "
                "0x1BCD60..0x2341C8 | per-cycle #3 0x2341CC..0x4BA840\n")
        f.write("# lines: 0xADDR  MNEMONIC OPERANDS  // annotations\n\n")
        for i in cpu.ins:
            a = i[0]
            if a in MARKER_DICT:
                buf.append("# " + MARKER_DICT[a])
                if len(buf) >= B:
                    f.write("\n".join(buf) + "\n")
                    buf = []
            # patch-list nodes are NOP'd (0x60000000) in the runnable code;
            # the generic decoder classifies them as `ori r0,r0,0` (op=24 is
            # checked before the nop fallback), so detect them by the raw word
            w = struct.unpack(">I", m.code[a:a + 4])[0]
            if w == 0x60000000:
                line = "0x%08x  nop    // [patch]" % a
            else:
                text, ann = fmt_ins(m, i)
                line = "0x%08x  %s" % (a, text)
                if ann:
                    line += "    // " + ann
            buf.append(line)
            n += 1
            if len(buf) >= B:
                f.write("\n".join(buf) + "\n")
                buf = []
        if buf:
            f.write("\n".join(buf) + "\n")
    print("written:", OUT, "lines:", n, "in %.1f s" % (time.time() - t0))


if __name__ == "__main__":
    main()
