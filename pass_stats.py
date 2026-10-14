#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pass_stats.py -- per-pass summary of the recovered netlist.

Prints, for each evaluation pass (the load-time init and the two per-cycle
passes), how many statements were recovered, how they decompose (constant
drivers, plain wire copies, boolean cones, whole-word copies, vector
assembly), and how large the largest cones are.  This is the table that shows
*why* the init pass is qualitatively different from the per-cycle ones.
"""
import collections
import json
import sys
import time

import netlist_slice as ns
from netlist_stream import Stream

TAB = {"init": "init", "cycle1": "cycle0_stage1", "cycle2": "cycle0_stage3"}


def has_field(n):
    """True if the expression contains a bit-packing (vector) atom.

    The stack holds *literals* `(sign, atom)` and clauses; the visited set is
    keyed by the node itself (tuples of frozensets are hashable), because
    expressions are shared DAGs and a naive walk revisits nodes
    exponentially."""
    seen = set()
    stack = [n]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if ns.is_clause(cur):
            # a clause's members are literals
            for lit in ns.clause_lits(cur):
                stack.append(lit)
            continue
        if not (isinstance(cur, tuple) and len(cur) == 2
                and isinstance(cur[0], int)):
            continue
        a = cur[1]
        if not isinstance(a, tuple) or not a:
            continue
        if a[0] == 'f':
            return True
        if ns.is_clause(a):
            stack.append(a)
    return False


def classify_stmt(st):
    """mutually exclusive class of one statement"""
    a, b, slot, v, bmask, wsrc = ns.stmt_parts(st)
    if bmask == 0:
        return "word-copy"
    if ns.is_clause(v):
        return "cone-vector" if has_field(v) else "cone"
    s, atom = v
    if atom[0] == 'c':
        return "constant"
    if atom[0] == 's':
        return "wire-copy"
    if atom[0] == 'f':
        return "vector"
    return atom[0]


def main():
    s = Stream()
    d, _ = ns.load_trace()
    regs = json.load(open("research/gt_regs.json"))
    print("%-7s %8s %8s %7s %7s %7s %9s %7s %8s" %
          ("pass", "stmts", "wires", "const", "wire", "cone", "cone+vect",
           "vector", "megacone"))
    for r in ("init", "cycle1", "cycle2"):
        t0 = time.time()
        sl = ns.Slicer(s, {}, regvals=regs[TAB[r]])
        sl.run_pass(ns.order_for(d, r))
        kinds = collections.Counter()
        slots = set()
        mega = 0
        big = 0
        for st in sl.statements:
            a, b, slot, v, bmask, wsrc = ns.stmt_parts(st)
            slots.add((b, slot))
            kinds[classify_stmt(st)] += 1
            n = ns.node_count(v, 4096)
            if n > big:
                big = n
            if n >= 4096:
                mega += 1
        print("%-7s %8d %8d %7d %7d %7d %9d %7d %8d   (%.1fs, largest cone "
              "%d)"
              % (r, len(sl.statements), len(slots), kinds["constant"],
                 kinds["wire-copy"], kinds["cone"], kinds["cone-vector"],
                 kinds["vector"] + kinds["word-copy"], mega,
                 time.time() - t0, big))


if __name__ == "__main__":
    main()
