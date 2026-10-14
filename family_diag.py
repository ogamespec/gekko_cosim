#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
family_diag.py -- find why family aggregation is slow in the init pass.

Prints, for the init pass, the statements with the largest expression node
counts (a few can be enormous because the generated code chains a whole
address-decode cone into one register).
"""
import collections
import json
import sys
import time

import netlist_slice as ns
from netlist_stream import Stream


def node_count(n, limit=10 ** 9):
    """delegate to the shared, identity-keyed walk (netlist_slice.graph_nodes)

    An earlier value-hashed version of this counter over-counted badly: nodes
    are distinct objects, so a shared sub-expression reached by two paths was
    counted twice and a 1,372-node graph looked like 200,000+ nodes."""
    return ns.graph_nodes(n, limit)


def main():
    s = Stream()
    d, _ = ns.load_trace()
    regs = json.load(open("research/gt_regs.json"))
    sl = ns.Slicer(s, {}, regvals=regs["init"])
    sl.run_pass(ns.order_for(d, "init"))
    print("statements:", len(sl.statements), flush=True)
    sizes = []
    t0 = time.time()
    for k, (a, b, sl2, v) in enumerate(sl.statements):
        sizes.append((node_count(v), a, b, sl2, v))
        if k % 5000 == 0:
            print("  counted %d in %.1fs" % (k, time.time() - t0), flush=True)
    sizes.sort(reverse=True, key=lambda t: t[0])
    print("node-count distribution (top 10):", [x[0] for x in sizes[:10]])
    print("total nodes:", sum(x[0] for x in sizes))
    hist = collections.Counter()
    for n, *_ in sizes:
        hist[min(n, 10)] += 1
    print("histogram (>=10 grouped):", sorted(hist.items()))
    for n, a, b, sl2, v in sizes[:3]:
        print("\n@%08x b%d.%04x nodes=%d" % (a, b, sl2, n))
        print("   %s" % ns.fmt(v)[:300])


if __name__ == "__main__":
    main()
