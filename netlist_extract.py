#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netlist_extract.py -- dump the compiled GKO netlist as a structured
instruction stream for motif ("gene") mining.

The model `model/COSIM.m2630opt.Jul1599` is a flat PowerPC program: a
compiled 2-value (0/1) netlist.  The code is a dense sequence of evaluation
cells; the *patch list* (38,738 link words) is overwritten with
`0x60000000` (nop) at load time, so those words are anchor holes: they are
executed by the CPU (branches count them) but they carry no logic.

This tool decodes the whole code region and stores one fixed-size record per
instruction word so that pattern mining can run without re-decoding:

    record = (addr u32, mnem u8, raw u32, f0 u32, f1 u32,
              regA u8, regB u8, regC u8, slot u16, flags u8, pad u8)  -- 24 B

  * `mnem`  -- token id of the mnemonic (the "DNA alphabet"); the patch nops
               get their own token `NOP` so they can be *skipped* when
               matching, but their positions stay in the stream.
  * `raw`   -- the 32-bit instruction word (exact bytes, for re-decoding).
  * `f0..f2`-- decoded fields (rt/ra/sd/imm/sh/mb/me/branch targets), meaning
               depends on the mnemonic (see FIELDS below).
  * `regA..C` -- register numbers (rt, ra, rb), so operand *shapes* can be
               compared across pattern instances.
  * `slot`  -- for loads/stores through the state banks r13..r20: the 16-bit
               wire slot = disp & 0xFFFF (disp<0 folds into 0x8000..0xFFFF);
               `bank` is regA-13 when the base register is a bank pointer.
  * `flags` -- F_PATCH (this word was a patch node), F_BANK (base register is
               a bank pointer), F_UNKNOWN (capstone could not decode).

Usage:
    python3 netlist_extract.py                 # -> research/netlist_ins.bin
    python3 netlist_extract.py --stats         # print a token histogram
"""
import argparse
import importlib.util
import os
import struct
import sys

MODEL = "model/COSIM.m2630opt.Jul1599"
PINLIST = "model/pin.list"
OUT = "research/netlist_ins.bin"

# code regions (bootstrap seams), see cosim.py / disasm_full.py
CODE_END = 0x4BA840
REGIONS = [
    (0x2C, 0x1BCD60, "init"),
    (0x1BCD60, 0x2341C8, "cycle1"),
    (0x2341CC, CODE_END, "cycle2"),
]

# Fixed-size record, 29 bytes.  Fields (index -> meaning):
#   0 addr u32 | 1 mnem u8 | 2 raw u32 | 3 f0 | 4 f1 | 5 f2 (u32 each) |
#   6 regs u32 (rs | ra<<8 | rb<<16) | 7 slot u16 | 8 flags u8 | 9 pad u8
# NOTE: struct.unpack returns 10 values -- the trailing pad byte is dropped.
REC = struct.Struct(">IBIIIIIHBB")
REC_SIZE = REC.size              # 29
F_ADDR, F_TKN, F_RAW, F_RG = 0, 1, 2, 6
F_SLO, F_FLG = 7, 8

BANK_REGS = (13, 14, 15, 16, 17, 18, 19, 20)

F_PATCH = 1
F_BANK = 2
F_UNKNOWN = 4
F_MEM = 8

MON = []          # token id -> mnemonic (index = id)
MON_ID = {}       # mnemonic -> token id
NOP_ID = None


def tok(name):
    """Intern a mnemonic into the token alphabet."""
    global NOP_ID
    i = MON_ID.get(name)
    if i is None:
        i = len(MON)
        MON_ID[name] = i
        MON.append(name)
        if name == "nop":
            NOP_ID = i
    return i


def load_model(path=MODEL):
    spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
    cosim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cosim)
    m = cosim.Model(path, PINLIST)
    return cosim, m


# field layout per mnemonic class -------------------------------------------
# 'D(ra),d'  load/store      -> f0=d, regA=ra, regB=rt
# 'rD,rA,rB' logic/arith    -> regA=rA, regB=rB, regC=rD
# 'rD,rA,imm' addi/ori/...  -> f0=imm, regA=rA, regC=rD
# 'rD,rA,sh,mb,me' rotate   -> f0=sh, f1=mb, f2=me
# 'cr,bi,addr' branch       -> f0=bo, f1=bi, f2=target
LS_MNEM = {"lbz", "lhz", "lha", "lwz", "lmw", "stb", "sth", "stw", "stmw",
           "lbzu", "lwzu", "stbu", "sthu", "stwu"}
LOGIC3 = {"and", "andc", "or", "orc", "nor", "nand", "xor", "eqv", "add",
          "subfc", "and.", "or.", "xor.", "nand.", "nor.", "add."}
IMM_MNEM = {"addi", "addis", "ori", "oris", "xori", "xoris", "mulli",
            "cmplwi", "cmpwi", "subfic", "addic", "srawi"}
ROT_MNEM = {"rlwinm", "rlwimi", "slwi", "srwi", "rlwnm", "extlwi", "extrwi",
            "rotlwi", "rotrwi", "clrlwi", "srw", "slw"}


def parse_mem(op_str):
    """'rD, d(rA)' -> (rt, ra, d)"""
    try:
        rd, rest = op_str.split(",", 1)
        d, ra = rest.strip().split("(")
        return int(rd[1:]), int(ra.rstrip(")")[1:]), int(d, 0)
    except Exception:
        return 0, 0, 0


def parse_regs(op_str):
    """register numbers in operand order (ignores immediates)"""
    out = []
    for part in op_str.split(","):
        p = part.strip()
        if p.startswith("r") and p[1:].isdigit():
            out.append(int(p[1:]))
    return out


def parse_imm(op_str):
    """the last operand if it is not a register"""
    parts = [p.strip() for p in op_str.split(",")]
    if not parts:
        return 0
    p = parts[-1]
    if p.startswith("r") and p[1:].isdigit():
        return 0
    try:
        return int(p, 0) & 0xFFFFFFFF
    except Exception:
        return 0


def branch_fields(op_str):
    """beq/bne 'cr,bi,addr' or plain 'addr' -> (bo, bi, target)"""
    parts = [p.strip() for p in op_str.split(",")]
    try:
        if len(parts) == 3:
            return int(parts[0].split()[0], 0), int(parts[1], 0), \
                int(parts[2], 0)
        if len(parts) == 1:
            p = parts[0]
            if p.startswith("0x"):
                return 0, 0, int(p, 0)
    except Exception:
        pass
    return 0, 0, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("-o", "--out", default=OUT)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    from capstone import Cs, CS_ARCH_PPC, CS_MODE_BIG_ENDIAN, CS_MODE_32
    cosim, m = load_model(args.model)
    code = m.code
    md = Cs(CS_ARCH_PPC, CS_MODE_BIG_ENDIAN | CS_MODE_32)

    tok("nop")                       # monkey-patch token for anchors
    recs = bytearray()
    stats_addr = {}
    unknown = 0
    patch_words = 0

    for start, end, label in REGIONS:
        for a in range(start, end, 4):
            raw = struct.unpack(">I", code[a:a + 4])[0]
            if raw == 0x60000000:
                recs += REC.pack(a, NOP_ID, raw, 0, 0, 0, 0, 0,
                                 F_PATCH | F_MEM, 0)
                patch_words += 1
                continue
            ins = next(md.disasm(code[a:a + 4], a), None)
            if ins is None:
                unknown += 1
                recs += REC.pack(a, tok("??"), raw, 0, 0, 0, 0, 0,
                                 F_UNKNOWN, 0)
                continue
            mn, ops = ins.mnemonic, ins.op_str
            f0 = f1 = f2 = 0
            rA = rB = rC = rD = 0
            slot = 0
            flags = 0
            if mn in LS_MNEM:
                rC, rA, f0 = parse_mem(ops)
                flags |= F_MEM
                if rA in BANK_REGS:
                    flags |= F_BANK
                    slot = f0 & 0xFFFF
            elif mn in LOGIC3:
                rs = parse_regs(ops)
                if len(rs) >= 3:
                    rC, rA, rB = rs[0], rs[1], rs[2]
                elif len(rs) == 2:
                    rC, rA = rs[0], rs[1]
            elif mn in IMM_MNEM:
                rs = parse_regs(ops)
                if rs:
                    rC = rs[0]
                if len(rs) > 1:
                    rA = rs[1]
                f0 = parse_imm(ops) & 0xFFFFFFFF
            elif mn in ROT_MNEM:
                rs = parse_regs(ops)
                if rs:
                    rC = rs[0]
                if len(rs) > 1:
                    rA = rs[1]
                nums = [int(p.strip(), 0) for p in ops.split(",")
                        if not p.strip().startswith("r")]
                if len(nums) >= 1:
                    f0 = nums[0]
                if len(nums) >= 2:
                    f1 = nums[1]
                if len(nums) >= 3:
                    f2 = nums[2]
            elif mn in ("beq", "bne", "bc", "b", "bl", "bdnz", "beqlr",
                        "bnelr", "bdnzlr"):
                f0, f1, f2 = branch_fields(ops)
            elif mn == "cmpw" or mn == "cmplw":
                rs = parse_regs(ops)
                if len(rs) >= 2:
                    rA, rB = rs[0], rs[1]
            elif mn == "mtlr" or mn == "mflr":
                rs = parse_regs(ops)
                if rs:
                    rA = rs[0]
            # Canonical architected register fields, stored as
            #   regs = rS | (rA << 8) | (rB << 16)
            # where rS/rD = bits 21..25, rA = bits 16..20, rB = bits 11..15.
            # Operand roles per form (this is the part generated code makes
            # easy to get wrong, so it is spelled out):
            #   X-form logic (and/andc/or/orc/nor/nand/xor/eqv/...):
            #           `op rS, rA, rB`  -> dest = rS, inputs = rA, rB
            #   addi/addis/li/lis/ori/oris/xori/xoris/mulli: `rD, rA, imm`
            #           -> dest = rS, base = rA
            #   loads  `rD, d(rA)` -> dest = rS, base = rA
            #   stores `rS, d(rA)` -> value = rS, base = rA
            #   rlwinm/rlwimi `rA, rS, sh, mb, me` -> dest = rA
            r_rd = ((raw >> 21) & 0x1F)
            r_ra = ((raw >> 16) & 0x1F)
            r_rb = ((raw >> 11) & 0x1F)
            try:
                recs += REC.pack(a, tok(mn), raw, f0 & 0xFFFFFFFF,
                                 f1 & 0xFFFFFFFF, f2 & 0xFFFFFFFF,
                                 r_rd | (r_ra << 8) | (r_rb << 16),
                                 slot & 0xFFFF, flags & 0xFF, 0)
            except struct.error as e:
                print("PACK FAIL @%x %s %s f0=%d f1=%d f2=%d raw=%08x "
                      "slot=%d flags=%d"
                      % (a, mn, ops, f0, f1, f2, raw, slot, flags))
                raise
            stats_addr[mn] = stats_addr.get(mn, 0) + 1

    with open(args.out, "wb") as f:
        f.write(struct.pack(">I", len(MON)))
        for s in MON:
            b = s.encode("latin1")
            f.write(struct.pack(">B", len(b)) + b)
        f.write(struct.pack(">I", len(recs) // REC_SIZE))
        f.write(recs)

    print("tokens: %d  instructions: %d (%d bytes) -> %s"
          % (len(MON), len(recs) // REC_SIZE, len(recs), args.out))
    print("patch nops: %d  undecoded words: %d" % (patch_words, unknown))

    if args.stats:
        for k, v in sorted(stats_addr.items(), key=lambda x: -x[1]):
            print("%10d  %s" % (v, k))


if __name__ == "__main__":
    main()
