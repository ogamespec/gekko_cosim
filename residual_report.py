#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
residual_report.py -- characterise what is left after verification.

Groups the slots where the recovered netlist disagrees with the compiled model
by the *kind* of atom in the driving expression, so the remaining error is
attributable rather than hand-waved:

  s   state wire        -- exact, inside the model
  p   memory image read -- exact only with a full memory snapshot
  c   constant          -- exact
  f   bit packing / address arithmetic -- one bit of a word assembled by the
                        compiler; the boolean part is recovered
  x   register input    -- a value the fragment inherits

Usage:  python residual_report.py [--pass cycle2] [--cycle 0]
"""
import argparse
import collections
import json
import os
import sys

import netlist_slice as ns
from netlist_stream import Stream

import verify_netlist as vn
from verify_final import evaluate

BANK_SIZE = 0x10000
STATE_DIR = "research/gt_state"


def atom_kinds(n, out):
    """count the atom kinds of an expression (iteratively: expressions are
    shared DAGs, so a recursive walk revisits nodes exponentially)"""
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
        if ns.is_clause(a):
            stack.append(a)
        else:
            out[a[0]] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="pas", default="cycle2",
                    choices=["cycle1", "cycle2"])
    ap.add_argument("--cycle", type=int, default=0)
    args = ap.parse_args()
    sys.setrecursionlimit(200000)

    s = Stream()
    d, _ = ns.load_trace()
    regvals = json.load(open("research/gt_regs.json"))
    rtab = {"cycle1": "cycle0_stage1", "cycle2": "cycle0_stage3"}[args.pas]

    if args.pas == "cycle1":
        pre_tag = "after_init"
        post_tag = "cycle%d_mid" % args.cycle
    else:
        pre_tag = "cycle%d_mid" % args.cycle
        post_tag = "cycle%d" % args.cycle
    pre = vn.load_banks(os.path.join(STATE_DIR, pre_tag + ".bin"))
    post = vn.load_banks(os.path.join(STATE_DIR, post_tag + ".bin"))
    mp = os.path.join(STATE_DIR, pre_tag + ".mem")
    ctxm = bytearray(open(mp, "rb").read()) if os.path.exists(mp) else \
        bytearray(vn.STATE_SIZE)

    sl = ns.Slicer(s, {}, regvals=regvals.get(rtab))
    sl.run_pass(ns.order_for(d, args.pas))
    last = evaluate(sl, pre, ctxm)

    kinds = collections.Counter()
    classes = collections.Counter()
    n_bad = 0
    for (bank, slot), (val, a, v, bmask, wsrc) in sorted(last.items()):
        if bmask == 0 and wsrc is not None:
            ok = pre[wsrc[1]][wsrc[2] & 0xFFFF] == post[bank][slot & 0xFFFF]
            cls = "word-copy"
        else:
            ok = post[bank][slot & 0xFFFF] == val
            cls = "bit-level"
        classes[(cls, ok)] += 1
        if ok:
            continue
        n_bad += 1
        if cls == "bit-level":
            atom_kinds(v, kinds)
    print("mismatching slots: %d / %d" % (n_bad, len(last)))
    for k, c in sorted(classes.items()):
        print("   %-10s %-5s %d" % (k[0], "ok" if k[1] else "BAD", c))
    print("atom kinds in the drivers of mismatching bit-level slots:")
    for k, c in kinds.most_common():
        print("   %-3s %d" % (k, c))


if __name__ == "__main__":
    main()
