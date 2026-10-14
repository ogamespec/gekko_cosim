#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
motif_hunt.py -- find the compiled logic-element patterns ("macroblocks") in
the executed part of the model.

Method (BLAST-like, as suggested in issue #1):

  1. restrict the strand to the code the simulator actually executes
     (ground truth from cosim.py, research/netlist_gt.json) -- the model file
     also contains a large amount of dead code from before the `m2630opt`
     optimisation, which must not pollute the pattern statistics;
  2. cut the strand into *linear* pieces: any transfer of control ends a
     piece, so every piece is a straight-line sequence of instructions;
  3. slide windows of k instructions over each piece and count them by
     operand-normalised *shape* (register numbers and offsets abstracted),
     exactly so that instances of one logic element match even though their
     ports differ;
  4. report the frequent shapes: those are the macroblocks.

Usage:
    python3 motif_hunt.py --k 3,4,5,6 --top 25
    python3 motif_hunt.py --contains and,nor --top 40
"""
import argparse
import collections
import json
import sys

from netlist_stream import Stream

LOGIC = {"and", "andc", "or", "orc", "nor", "nand", "xor", "eqv"}
LOAD1 = {"lbz"}
STORE1 = {"stb"}


def load_exec(path="research/gt_exec.json"):
    """executed addresses (ground truth from gt_dump.py)"""
    gt = json.load(open(path))
    return set(int(k, 16) for k in gt["exec_cnt"])


def linear_pieces(s, ex):
    """executed addresses split at every control-flow transfer.

    A piece ends when the next executed instruction is not the physically
    following word (branch taken / target) or the current instruction is a
    branch at all (so fall-through and target both start new pieces)."""
    addrs = sorted(ex)
    pieces = []
    cur = []
    for a in addrs:
        i = s.addr2i.get(a)
        if i is None:
            continue
        if cur:
            prev_a = cur[-1]
            if a != prev_a + 4 or s.mn[s.addr2i[prev_a]] in (
                    "b", "beq", "bne", "bc", "bdnz", "blr", "blrl"):
                pieces.append(cur)
                cur = []
        cur.append(a)
    if cur:
        pieces.append(cur)
    return pieces


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", default="3,4,5,6")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--contains", default=None,
                    help="comma list of mnemonics the window must contain")
    ap.add_argument("--region", default="all",
                    choices=["all", "init", "cycle1", "cycle2"])
    ap.add_argument("--shapes", action="store_true",
                    help="print the shapes of the top raw patterns")
    args = ap.parse_args()

    s = Stream()
    ex = load_exec()
    if args.region == "init":
        ex = set(a for a in ex if a < 0x1BCD60)
    elif args.region == "cycle1":
        ex = set(a for a in ex if 0x1BCD60 <= a < 0x2341C8)
    elif args.region == "cycle2":
        ex = set(a for a in ex if a >= 0x2341CC)
    pieces = linear_pieces(s, ex)
    print("strand: %d executed instructions in %d linear pieces"
          % (sum(len(p) for p in pieces), len(pieces)))

    want = set(args.contains.split(",")) if args.contains else None
    # only keep pieces that are pure data-flow (no calls, no asserts)
    for k in [int(x) for x in args.k.split(",")]:
        cnt = collections.Counter()
        pos = collections.Counter()
        for p in pieces:
            idx = [s.addr2i[a] for a in p]
            for t in range(len(idx) - k + 1):
                win = idx[t:t + k]
                mns = [s.mn[i] for i in win]
                if want and not want.issubset(set(mns)):
                    continue
                key = tuple(s.shape(i) for i in win)
                cnt[key] += 1
                pos[key] = (p[t], len(p))
        print("\n=== k=%d: %d distinct shapes ===" % (k, len(cnt)))
        for key, c in cnt.most_common(args.top):
            if c < 3:
                break
            a, ln = pos[key]
            print("%7d  %-58s  @%08x piece=%d"
                  % (c, " ".join(str(x) for x in key)[:58], a, ln))
            if args.shapes:
                for x in key:
                    print("             %s" % x)


if __name__ == "__main__":
    main()
