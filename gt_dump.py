#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gt_dump.py -- capture ground-truth state snapshots and the executed trace.

Runs the real cosim.py interpreter for a few cycles of model/pin.list with the
demo input map and saves, for each observation point:

    research/gt_state/<tag>.bin     8 x 65536 bytes = the state banks
                                    (bank b byte s = slot s of bank b)

together with the executed-address trace per pass.  `verify_netlist.py` uses
these snapshots to check the *reconstructed* netlist against the compiled
model: the extracted statements must turn the "before" banks into the
"after" banks.

Usage:  python3 gt_dump.py [--cycles 4] [--inputs inputs_demo.txt]
"""
import argparse
import importlib.util
import json
import os
import struct

spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
cosim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cosim)

MODEL = "model/COSIM.m2630opt.Jul1599"
PINLIST = "model/pin.list"
OUTDIR = "research/gt_state"
BANK_BASE = 0x8000
BANK_SIZE = 0x10000


def save_banks(cpu, tag):
    os.makedirs(OUTDIR, exist_ok=True)
    buf = bytearray()
    for b in range(8):
        base = BANK_BASE + b * BANK_SIZE
        buf += cpu.mem[base:base + BANK_SIZE]
    path = os.path.join(OUTDIR, tag + ".bin")
    with open(path, "wb") as f:
        f.write(buf)
    return path


def save_mem(cpu, tag):
    """the full interpreter state memory (needed to evaluate reads through
    non-bank pointers: the latch arrays the generated code walks)"""
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, tag + ".mem")
    with open(path, "wb") as f:
        f.write(bytes(cpu.mem))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=4)
    ap.add_argument("--inputs", default="inputs_demo.txt")
    args = ap.parse_args()

    m = cosim.Model(MODEL, PINLIST)
    cpu = cosim.CPU(m)

    exec_cnt = {}
    order = []            # exact execution order per pass (branch-aware:
                          # sorting addresses is NOT the same thing once there
                          # are backward branches)

    def hook(c, ins):
        exec_cnt[ins[0]] = exec_cnt.get(ins[0], 0) + 1
        order.append(ins[0])

    cpu.hook = hook
    print("init ...", flush=True)
    cpu.run(cosim.ENTRY_INIT, max_steps=2000000)
    init_order = list(order)
    order[:] = []
    save_banks(cpu, "after_init")
    save_mem(cpu, "after_init")
    print("  saved after_init (%d init instructions)" % len(init_order),
          flush=True)

    plan, order = cosim.parse_inputs(args.inputs) if args.inputs else ({}, [])
    pinwidth = {}
    for nm, msb, lsb in (m.pinlist or []):
        pinwidth[nm] = abs(msb - lsb) + 1
    pinvals = {}

    passes = {}
    for cyc in range(args.cycles):
        for pn, v in plan.get(cyc, {}).items():
            if cpu.set_pin(pn, v, pinwidth.get(pn)):
                try:
                    pinvals[pn] = int(v, 0)
                except Exception:
                    pass
        before = dict(exec_cnt)
        order[:] = []
        save_banks(cpu, "cycle%d_pre" % cyc)
        save_mem(cpu, "cycle%d_pre" % cyc)
        r1 = cpu.run(m.entry, max_steps=10000000)
        stage1_order = list(order)
        order[:] = []
        save_banks(cpu, "cycle%d_mid" % cyc)
        save_mem(cpu, "cycle%d_mid" % cyc)
        r3 = cpu.run(cosim.ENTRY_STAGE3, max_steps=100000000)
        stage3_order = list(order)
        order[:] = []
        n1 = cpu.steps
        passes["cycle%d" % cyc] = {
            "stage1": r1, "stage3": r3,
            "new_addrs": sorted(a for a in exec_cnt if a not in before),
            "order_stage1": stage1_order,
            "order_stage3": stage3_order,
        }
        save_banks(cpu, "cycle%d" % cyc)
        print("cycle %d: stage1=%s stage3=%s new=%d saved"
              % (cyc, r1, r3, len(passes["cycle%d" % cyc]["new_addrs"])),
              flush=True)

    with open("research/gt_exec.json", "w", encoding="utf-8") as f:
        json.dump({"exec_cnt": {("%08x" % k): v for k, v in exec_cnt.items()},
                   "passes": {k: v["new_addrs"] for k, v in passes.items()},
                   "init_order": init_order,
                   "order": {k: {"stage1": v["order_stage1"],
                                 "stage3": v["order_stage3"]}
                             for k, v in passes.items()},
                   "steps": {k: (v["stage1"], v["stage3"])
                             for k, v in passes.items()}},
                  f)
    print("written research/gt_exec.json, %d executed addresses"
          % len(exec_cnt))


if __name__ == "__main__":
    main()
