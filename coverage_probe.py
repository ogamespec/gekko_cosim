#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coverage_probe.py -- does other stimulus recover more of the netlist?

Runs N cycles of the model with a pin stimulus that keeps all top-level inputs
moving (bus values, cache/bus handshakes, interrupts), records which code
addresses execute, and reports the growing set of recovered store sites.  This
is the practical answer to "is this the whole netlist?": the recovered netlist
is complete for the *exercised* inputs, and the way to complete it is to
exercise more branches.

Usage:  python coverage_probe.py --cycles 12 --seed 1
"""
import argparse
import collections
import importlib.util
import json
import random

spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
cosim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cosim)

MODEL = "model/COSIM.m2630opt.Jul1599"
PINLIST = "model/pin.list"
STORES = (cosim.K_STB, cosim.K_STH, cosim.K_STW, cosim.K_STMW)

# a stimulus that keeps the chip busy: bus grants/tenures, data, interrupts
BUS_PINS = ["A", "DH", "DL", "DP", "TT", "TSIZ", "TS_", "TT_", "CI_", "WT_",
            "GBL_", "AP", "ARTRY_", "BR_", "BG_", "DBG_", "DRTRY_", "TEA_",
            "INT_", "SMI_", "MCP_", "SRESET_", "HRESET_", "TLBISYNC_", "TDO"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="research/coverage_probe.json")
    args = ap.parse_args()

    m = cosim.Model(MODEL, PINLIST)
    cpu = cosim.CPU(m)
    widths = {nm: abs(msb - lsb) + 1 for nm, msb, lsb in (m.pinlist or [])}
    rnd = random.Random(args.seed)

    exec_cnt = collections.Counter()
    store_sites = set()

    def hook(c, ins):
        exec_cnt[ins[0]] += 1
        if ins[1] in STORES and 13 <= ins[3] <= 20:
            store_sites.add(ins[0])

    cpu.hook = hook
    cpu.run(cosim.ENTRY_INIT, max_steps=2000000)
    after_init = (len(exec_cnt), len(store_sites))
    print("after init: %d distinct addresses, %d bank-store sites"
          % after_init)

    busPins = [p for p in BUS_PINS if p in m.pins]
    per_cycle = []
    for cyc in range(args.cycles):
        for p in busPins:
            w = widths.get(p, 1)
            if w == 1:
                cpu.set_pin(p, rnd.getrandbits(1))
            else:
                cpu.set_pin(p, rnd.getrandbits(min(w, 32)) & ((1 << w) - 1))
        cpu.run(m.entry, max_steps=10000000)
        cpu.run(cosim.ENTRY_STAGE3, max_steps=100000000)
        per_cycle.append((cyc, len(exec_cnt), len(store_sites)))
        print("cycle %2d: %7d distinct addresses, %6d store sites"
              % (cyc, len(exec_cnt), len(store_sites)))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"per_cycle": per_cycle,
                   "store_sites": sorted(store_sites),
                   "exec": {("%08x" % k): v for k, v in exec_cnt.items()}},
                  f)
    print("\nwritten %s" % args.out)
    print("store sites after init: %d, after %d busy cycles: %d"
          % (after_init[1], args.cycles, len(store_sites)))


if __name__ == "__main__":
    main()
