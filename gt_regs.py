#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gt_regs.py -- record the register file at every executed *bank store*.

The reconstructed statements contain `in_rN` atoms: values that entered the
fragment in a register (the interpreter knows them exactly, the netlist does
not have an explicit assignment for them -- they are latched values written by
an earlier, not-executed branch).  Recording the register file at every store
site makes every atom of every statement resolvable, so verification becomes
an exact equivalence check of the extracted netlist rather than an
approximation.

Inputs (already produced by gt_dump.py):  research/gt_exec.json
Output:                                   research/gt_regs.json
    { "<pass>": { "<addr>:<occurrence>": [r0..r31] } }

Usage:  python3 gt_regs.py [--cycles 1]
"""
import argparse
import importlib.util
import json

spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
cosim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cosim)

MODEL = "model/COSIM.m2630opt.Jul1599"
PINLIST = "model/pin.list"
STORES = (cosim.K_STB, cosim.K_STH, cosim.K_STW, cosim.K_STMW)
BANK_REGS = range(13, 21)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--inputs", default="inputs_demo.txt")
    ap.add_argument("--out", default="research/gt_regs.json")
    args = ap.parse_args()

    m = cosim.Model(MODEL, PINLIST)
    cpu = cosim.CPU(m)

    out = {}
    occ = {}

    def make_hook(tag):
        """record the register file at every executed instruction.

        Statements can contain *field* atoms (bit packing / address
        arithmetic) whose value is fixed where the instruction computed it --
        that may be far from the store, and the two sites need not be reached
        the same number of times, so keying by (address, occurrence) at every
        instruction is the only exact option."""
        tbl = out.setdefault(tag, {})
        seen = occ.setdefault(tag, {})

        def hook(c, ins):
            a = ins[0]
            n = seen.get(a, 0)
            seen[a] = n + 1
            tbl["%08x:%d" % (a, n)] = list(c.r)
        return hook

    cpu.hook = make_hook("init")
    print("init ...", flush=True)
    cpu.run(cosim.ENTRY_INIT, max_steps=2000000)
    print("  init sites: %d" % len(out["init"]), flush=True)

    plan, order = cosim.parse_inputs(args.inputs) if args.inputs else ({}, [])
    pinwidth = {}
    for nm, msb, lsb in (m.pinlist or []):
        pinwidth[nm] = abs(msb - lsb) + 1

    for cyc in range(args.cycles):
        for pn, v in plan.get(cyc, {}).items():
            cpu.set_pin(pn, v, pinwidth.get(pn))
        cpu.hook = make_hook("cycle%d_stage1" % cyc)
        cpu.run(m.entry, max_steps=10000000)
        cpu.hook = make_hook("cycle%d_stage3" % cyc)
        cpu.run(cosim.ENTRY_STAGE3, max_steps=100000000)
        print("  cycle %d: stage1 sites %d, stage3 sites %d"
              % (cyc, len(out["cycle%d_stage1" % cyc]),
                 len(out["cycle%d_stage3" % cyc])), flush=True)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print("written %s (%d tables)" % (args.out, len(out)))


if __name__ == "__main__":
    main()
