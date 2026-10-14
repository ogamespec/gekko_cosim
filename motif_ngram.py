#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
motif_ngram.py -- step 1 of the macroblock recovery: count repeated opcode
"N-grams" in the compiled netlist instruction stream.

Nothing here assumes anything about cell/cell boundaries: a logic element may
straddle the 0x80-byte anchor grid, so the code is treated as one long DNA
strand and recurring substrings are counted directly (BLAST-style, with the
patch NOPs acting as introns: they never take part in a pattern, but their
presence is recorded).

Two alphabets are counted for each window length k:
  * RAW     -- token id of the mnemonic, exact sequence (NOPs skipped);
  * SHAPE   -- mnemonic + operand *shape* (which register is a destination /
               a source / a bank pointer / a literal), so that instances
               differing only in register numbers or offsets hash to the same
               key, exactly as the issue describes.

Usage:
    python3 motif_ngram.py --k 4,5,6,7,8,10,12 --top 40
"""
import argparse
import collections
import struct
import sys

REC = struct.Struct(">IBIIIBBBBHBB")
REC_SIZE = REC.size

KIND = ["lbz", "lhz", "lha", "lwz", "lmw", "stb", "sth", "stw", "stmw"]
ROT = ["rlwinm", "rlwimi", "rlwnm", "slwi", "srwi", "srawi", "extlwi",
       "extrwi", "rotlwi", "clrlwi", "slw", "srw"]
BR = ["b", "beq", "bne", "bc", "bdnz", "bl", "beqlr", "bnelr", "bdnzlr",
      "blr", "blrl", "mtlr", "mflr"]


def load(path):
    """use the shared loader so the record layout lives in exactly one place"""
    from netlist_stream import Stream
    s = Stream(path)
    return s.mon, s.recs


def shape_key(mon, r):
    """mnemonic + operand shape (register numbers erased).

    Record fields: 0 addr | 1 token | 2 raw | 3 f0 | 4 f1 | 5 f2 |
    6 regs (rt | ra<<8 | rb<<16) | 7 slot | 8 flags | 9 pad."""
    a, t, raw, f0, f1, f2, rg, slot, flags = r[:9]
    mn = mon[t]
    if mn in ("nop", "??"):
        return mn
    parts = [mn]
    if flags & 2:                       # base register is a state bank
        parts.append("bank")
    elif mn in KIND or mn in ("addi", "addis", "ori", "oris", "xori",
                              "xoris", "mulli", "cmplwi", "cmpwi"):
        parts.append("-")
    else:
        parts.append("r")
    if mn in KIND:
        if slot:
            parts.append("slot")
        else:
            parts.append("off")
    elif mn in ("beq", "bne", "bc", "bdnz"):
        parts.append("bo%d" % f0)
    elif mn in ("b", "bl"):
        parts.append("-")
    elif mn in ROT:
        parts.append("r")
    return "|".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="research/netlist_ins.bin")
    ap.add_argument("--k", default="3,4,5,6,7,8,10,12,16")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--alphabet", default="shape", choices=["shape", "raw"])
    args = ap.parse_args()

    mon, recs = load(args.input)
    print("stream: %d instructions, %d mnemonics" % (len(recs), len(mon)))

    nop = mon.index("nop")
    if args.alphabet == "shape":
        alpha = [shape_key(mon, r) for r in recs]
    else:
        alpha = [mon[r[1]] for r in recs]
    # second alphabet: exact mnemonics only
    alpha2 = [(None if r[1] == nop else mon[r[1]]) for r in recs]

    ks = [int(x) for x in args.k.split(",")]
    for k in ks:
        # windows of k *non-nop* tokens: build an index of the non-nop
        # positions, then windows are sequences of positions
        pos = [i for i, a in enumerate(alpha2) if a is not None]
        cnt = collections.Counter()
        cnt2 = collections.Counter()
        ex = {}
        for s in range(len(pos) - k + 1):
            idx = pos[s:s + k]
            # a window is only interesting if consecutive (no giant jump)
            if idx[-1] - idx[0] > 4 * k:
                continue
            key = tuple(alpha[i] for i in idx)
            cnt[key] += 1
            if cnt[key] == 1:
                ex[key] = idx[0]
            key2 = tuple(alpha2[i] for i in idx)
            cnt2[key2] += 1
        print("\n=== k=%d : %d distinct shape-grams, %d distinct raw-grams ==="
              % (k, len(cnt), len(cnt2)))
        print("-- by operand SHAPE (register/offset insensitive) --")
        for key, c in cnt.most_common(args.top):
            if c < 2:
                break
            print("%8d  %s" % (c, " ".join(key)))
        print("-- by exact MNEMONIC --")
        for key, c in cnt2.most_common(min(args.top, 15)):
            if c < 2:
                break
            print("%8d  %s" % (c, " ".join(key)))


if __name__ == "__main__":
    main()
