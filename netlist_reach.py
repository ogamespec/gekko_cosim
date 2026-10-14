#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netlist_reach.py -- how much of the compiled netlist is in the recovered set,
and how much code could still be reached with other stimulus.

Two separate questions, answered separately:

1. **Completeness of the recovered netlist for the exercised trace.**  Every
   store executed by the interpreter is compared with the statements the
   slicer produced; the sets must be identical (they are -- see
   `block_partition.py`).

2. **How much logic was never exercised.**  The interpreter only runs the
   branches its inputs select, so a wire can be driven by code that never ran
   under `inputs_demo.txt`.  This tool enumerates the code *statically
   reachable* from the model's entry points (following fall-through and all
   branch targets), collects every bank store in that set, and reports how
   many of them the executed trace covered.  The difference is an upper bound
   on the logic missing from the recovered netlist.

Usage:  python netlist_reach.py
"""
import collections
import json
import sys

import netlist_slice as ns
from netlist_stream import Stream

STORES = ("stb", "sth", "stw", "stmw")
BRANCHES = ("b", "beq", "bne", "bc", "bdnz")
ENTRIES = (0x2C, 0x1BCD60, 0x2341CC)
CODE_END = 0x4BA840


def static_reachable(s):
    """addresses reachable from the entry points by fall-through + branches"""
    todo = list(ENTRIES)
    seen = set()
    n = len(s.recs)
    while todo:
        a = todo.pop()
        while a < CODE_END:
            if a in seen:
                break
            seen.add(a)
            i = s.addr2i.get(a)
            if i is None:
                break
            mn = s.mn[i]
            if mn in BRANCHES:
                tgt = s.recs[i][5]
                if 0 < tgt < CODE_END:
                    todo.append(tgt)
                if mn == "b":
                    break           # unconditional: no fall-through
            elif mn in ("blr", "blrl"):
                break               # returns: caller-dependent
            a += 4
    return seen


def main():
    s = Stream()
    d, _ = ns.load_trace()

    ex = set()
    for r in ("init", "cycle1", "cycle2"):
        ex.update(a for a in ns.order_for(d, r))
    static = static_reachable(s)
    print("code region words: %d" % ((CODE_END - 0x2C) // 4))
    print("statically reachable from the entries: %d (%.1f %%)"
          % (len(static), 100.0 * len(static) / ((CODE_END - 0x2C) // 4)))
    print("actually executed: %d (%.1f %% of reachable)"
          % (len(ex), 100.0 * len(ex) / max(1, len(static))))

    def stores(addrs):
        out = set()
        for a in addrs:
            i = s.addr2i.get(a)
            if i is None:
                continue
            if s.mn[i] in STORES and s.bank[i] >= 0:
                out.add(a)
        return out

    st_static = stores(static)
    st_exec = stores(ex)
    print()
    print("bank-store instructions, statically reachable: %d" % len(st_static))
    print("bank-store instructions, executed:              %d" % len(st_exec))
    missing = st_static - st_exec
    print("reachable but NOT executed:                     %d (%.1f %%)"
          % (len(missing), 100.0 * len(missing) / max(1, len(st_static))))
    if missing:
        addrs = sorted(missing)
        print("  address histogram (0x100000 pages):")
        h = collections.Counter(a >> 20 for a in addrs)
        for k in sorted(h):
            print("     0x%x00000-0x%xfffff : %d" % (k, k, h[k]))


if __name__ == "__main__":
    sys.setrecursionlimit(200000)
    main()
