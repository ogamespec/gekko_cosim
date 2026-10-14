#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pin_refs.py -- where the pins live in the recovered netlist.

`model/pin.list` declares the top-level pins; the model's own pin table
(`cosim.py: Model._pin_table`, extracted from the binary) maps each pin to
state slots.  Pins are *inputs*: the test bench (MVLSIM / cosim.py) writes them
into the state banks before each cycle, so in the netlist they only ever
appear on the right-hand side -- the compiled logic reads them, it never
drives them.

This tool lists every statement of the recovered netlist that reads a pin
slot, which is the netlist's view of the model's inputs.

Usage:  python pin_refs.py [--region cycle2] [--emit research/pin_refs.txt]
"""
import argparse
import collections
import importlib.util
import json
import sys

import netlist_slice as ns
from netlist_stream import Stream


def parse_pins(model_path, pinlist_path):
    spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
    cosim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cosim)
    m = cosim.Model(model_path, pinlist_path)
    return m


def slots_of(n, out):
    """collect (bank, slot) read by an expression"""
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
            out.append((a[1], a[2]))
        elif ns.is_clause(a):
            stack.append(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="cycle2",
                    choices=["init", "cycle1", "cycle2"])
    ap.add_argument("--emit", default=None)
    ap.add_argument("--pin-min", type=lambda x: int(x, 0), default=0xE800)
    ap.add_argument("--pin-max", type=lambda x: int(x, 0), default=0xEBFF)
    args = ap.parse_args()
    sys.setrecursionlimit(200000)

    m = parse_pins("model/COSIM.m2630opt.Jul1599", "model/pin.list")
    names = m.slot_names

    # pin name -> set of slots (only the >= 0x8000 form addresses the banks)
    pin_of_slot = collections.defaultdict(set)
    for nm, sl in m.pins.items():
        for s in sl:
            if s >= args.pin_min:
                pin_of_slot[s].add(nm)

    s = Stream()
    d, _ = ns.load_trace()
    tab = {"init": "init", "cycle1": "cycle0_stage1",
           "cycle2": "cycle0_stage3"}[args.region]
    regs = json.load(open("research/gt_regs.json"))
    sl_ = ns.Slicer(s, {}, regvals=regs.get(tab))
    sl_.run_pass(ns.order_for(d, args.region))

    hits = []
    reads = collections.Counter()
    n_write = 0
    for st in sl_.statements:
        a, bank, slot, v, bmask, wsrc = ns.stmt_parts(st)
        if bmask == 0:
            r = [(wsrc[1], wsrc[2])] if wsrc else []
        else:
            r = []
            slots_of(v, r)
        for (b, sl2) in r:
            if args.pin_min <= sl2 <= args.pin_max and b == 2:
                pins = ",".join(sorted(pin_of_slot.get(sl2, {"?"})))
                reads[(b, sl2, pins)] += 1
                hits.append((a, bank, slot, b, sl2, pins))
        if args.pin_min <= slot <= args.pin_max:
            n_write += 1

    print("region %s: %d statements" % (args.region, len(sl_.statements)))
    print("statements WRITING a pin-range slot: %d" % n_write)
    print("statements READING a pin-range slot: %d" % len(hits))
    print("\npin slots read (bank 2), by pin name claimed by the model table:")
    for (b, sl2, pins), c in sorted(reads.items(), key=lambda kv: -kv[1])[:20]:
        nm = names.get(sl2, "")
        print("   slot %04x  %-28s x%-3d  internal name: %s"
              % (sl2, pins, c, nm or "-"))
    if args.emit:
        with open(args.emit, "w", encoding="utf-8") as f:
            f.write("# Statements of the recovered netlist that read a "
                    "top-level pin\n")
            f.write("# region: %s\n" % args.region)
            f.write("# format: @addr  dst  <= ...  | read pin slot 0xXXXX "
                    "(pin names, internal name)\n")
            for a, bank, slot, b, sl2, pins in hits:
                f.write("@%08x  b%d.%04x  | reads slot 0x%04x  pins=%s  "
                        "internal=%s\n"
                        % (a, bank, slot, sl2, pins,
                           names.get(sl2, "-")))
        print("\nwritten", args.emit)


if __name__ == "__main__":
    main()
