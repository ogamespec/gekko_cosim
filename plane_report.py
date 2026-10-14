#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plane_report.py -- which state bank (plane) a statement writes, and which
planes its expression reads from.

The 8 banks are 4 plane-pairs of the two-value simulation (L1/L2 latch phases),
so "which plane" is not cosmetic: it says which copy of a wire the compiled
code reads and which it commits to.  This matters when reading the emitted
netlist, because a name carrying `.L1`/`.L2` identifies the *schematic* latch
phase of the wire, while the bank number says which simulation copy the
statement touched.

Usage:  python plane_report.py [--region cycle2]
"""
import argparse
import collections
import json
import sys

import netlist_slice as ns
from netlist_stream import Stream


def read_banks(n, out):
    """banks the expression reads (literals whose atom is a state wire)"""
    seen = set()
    stack = [n]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if ns.is_clause(cur):
            for lit in ns.clause_lits(cur):
                stack.append(lit)
            continue
        if not (isinstance(cur, tuple) and len(cur) == 2
                and isinstance(cur[0], int)):
            continue
        a = cur[1]
        if not isinstance(a, tuple) or not a:
            continue
        if a[0] == 's':
            out[a[1]] += 1
        elif ns.is_clause(a):
            stack.append(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="cycle2",
                    choices=["init", "cycle1", "cycle2"])
    args = ap.parse_args()
    sys.setrecursionlimit(200000)

    s = Stream()
    d, _ = ns.load_trace()
    regs = json.load(open("research/gt_regs.json"))
    tab = {"init": "init", "cycle1": "cycle0_stage1",
           "cycle2": "cycle0_stage3"}[args.region]
    sl = ns.Slicer(s, {}, regvals=regs.get(tab))
    sl.run_pass(ns.order_for(d, args.region))

    writes = collections.Counter()
    reads = collections.Counter()
    pairs = collections.Counter()
    n_plain = 0
    for st in sl.statements:
        a, b, slot, v, bmask, wsrc = ns.stmt_parts(st)
        if bmask == 0:                      # whole-word copy
            writes[b] += 1
            if wsrc:
                reads[wsrc[1]] += 1
                pairs[(wsrc[1], b)] += 1
            continue
        writes[b] += 1
        rb = collections.Counter()
        read_banks(v, rb)
        if ns.is_clause(v):
            n_plain += 1
        for k, c in rb.items():
            reads[k] += c
            pairs[(k, b)] += 1

    print("region %s: %d statements" % (args.region, len(sl.statements)))
    print("writes per bank (plane):",
          sorted(writes.items()))
    print("reads per bank (plane): ", sorted(reads.items()))
    print("\nmost common (read plane -> write plane) flows:")
    for (r, w), c in pairs.most_common(12):
        print("   bank %d -> bank %d : %d" % (r, w, c))


if __name__ == "__main__":
    main()
