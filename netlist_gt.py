#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netlist_gt.py -- ground truth from the interpreter.

Runs the real cosim.py interpreter (init pass + N model cycles) with a
per-instruction hook, so every statement below is measured, not inferred:

  * which code addresses are actually executed, and how often;
  * for every memory access, the effective state address and -- for accesses
    through the state banks r13..r20 -- the (bank, slot) pair;
  * for accesses through any other base register, the observed absolute
    address range: this identifies the *planes* the generated code walks
    (the bank bases are only 8 of the many base pointers the code uses);
  * the register values at the start of each per-cycle pass.

Output: research/netlist_gt.json
"""
import collections
import importlib.util
import json

spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
cosim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cosim)

MODEL = "model/COSIM.m2630opt.Jul1599"
PINLIST = "model/pin.list"
OUT = "research/netlist_gt.json"

LS = (cosim.K_LBZ, cosim.K_LHZ, cosim.K_LHA, cosim.K_LWZ, cosim.K_LMW,
      cosim.K_STB, cosim.K_STH, cosim.K_STW, cosim.K_STMW)

exec_cnt = collections.Counter()      # code addr -> executions
loaded = collections.Counter()        # (bank,slot) -> loads
stored = collections.Counter()        # (bank,slot) -> stores
planereg = {}                         # reg -> [lo, hi, count, samples]
passes = []                           # per-pass statistics


def make_hook(tag):
    def hook(cpu, ins):
        a, k = ins[0], ins[1]
        exec_cnt[a] += 1
        if k in LS:
            ra, d = ins[3], ins[4]
            addr = (cpu.r[ra] + d) & 0xFFFFFFFF
            is_store = k in (cosim.K_STB, cosim.K_STH, cosim.K_STW,
                             cosim.K_STMW)
            if 13 <= ra <= 20:
                key = (ra - 13, d & 0xFFFF)
                (stored if is_store else loaded)[key] += 1
            else:
                e = planereg.get(ra)
                if e is None:
                    planereg[ra] = [addr, addr, 1, [addr]]
                else:
                    e[0] = min(e[0], addr)
                    e[1] = max(e[1], addr)
                    e[2] += 1
                    if len(e[3]) < 6:
                        e[3].append(addr)
    return hook


def main():
    m = cosim.Model(MODEL, PINLIST)
    cpu = cosim.CPU(m)

    print("build date %s, patch nodes %d, named slots %d"
          % (m.build_date, m.patch_count, len(m.slot_names)), flush=True)

    cpu.hook = make_hook("init")
    print("init pass (0x%x) ..." % cosim.ENTRY_INIT, flush=True)
    r = cpu.run(cosim.ENTRY_INIT, max_steps=2000000)
    print("init: %s steps=%d exec=%d" % (r, cpu.steps, len(exec_cnt)),
          flush=True)
    passes.append(("init", r, cpu.steps, len(exec_cnt), dict(planereg)))
    init_regs = list(cpu.r)

    # one full cycle: stage1 (fast path) + stage3 (full netlist)
    for cyc in range(2):
        before = len(exec_cnt)
        cpu.hook = make_hook("c%d" % cyc)
        r1 = cpu.run(m.entry, max_steps=10000000)
        r3 = cpu.run(cosim.ENTRY_STAGE3, max_steps=100000000)
        print("cycle %d: stage1=%s (%d steps) stage3=%s (%d steps) "
              "new addrs=%d" % (cyc, r1, cpu.steps, r3, cpu.steps,
                                len(exec_cnt) - before), flush=True)
        passes.append(("cycle%d" % cyc, r1, cpu.steps, len(exec_cnt),
                       dict(planereg)))

    # analyse the plane pointers
    print("\n== base registers other than r13..r20 (planes) ==")
    regs = []
    for reg, (lo, hi, cnt, samp) in sorted(planereg.items()):
        regs.append((reg, lo, hi, cnt, samp))
        print("  r%-2d addr 0x%08x..0x%08x (%d accesses)%s"
              % (reg, lo, hi, cnt,
                 "" if lo == hi else "  span 0x%x" % (hi - lo)))
    print("\nregister values after init:")
    for i, v in enumerate(init_regs):
        if v:
            print("  r%-2d = 0x%08x" % (i, v))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "exec_cnt": {("%08x" % k): v for k, v in sorted(exec_cnt.items())},
            "exec_count": len(exec_cnt),
            "planereg": {str(k): v for k, v in sorted(planereg.items())},
            "loaded": {("%d:%04x" % k): v for k, v in sorted(loaded.items())},
            "stored": {("%d:%04x" % k): v for k, v in sorted(stored.items())},
            "init_regs": init_regs,
            "passes": [(t, r, s, n) for t, r, s, n, _ in passes],
        }, f, indent=1)
    print("\nwritten", OUT)
    print("executed code addresses: %d" % len(exec_cnt))
    print("bank slots loaded: %d, stored: %d" % (len(loaded), len(stored)))


if __name__ == "__main__":
    main()
