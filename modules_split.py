#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modules_split.py -- split the recovered netlist into one file per original
source module, in `research/modules/`.

The model's symbol table keeps the design hierarchy in the wire names
(`GKO.<BLOCK>.<signal>…`), so every statement -- which writes exactly one state
wire -- can be routed back to the block it belongs to:

  * if the driven wire has a symbol name, that name gives the block;
  * otherwise (most wires are nameless local cones) the block is taken from the
    dominant block of the 4 KiB code bucket the statement executed from: the
    compiled code is laid out block by block.

Output:
    research/modules/<BLOCK>.txt     one file per module, all its statements
    research/modules/README.md       index: block, statement counts, drive

Statement line format:

    @<code addr>  b<bank>.<slot>  <signal name>  <=  <expression>

Expressions are printed with depth/width/length caps (long clauses end in
`... N more...`); for a fully faithful rendering of one statement use
`python netlist_slice.py --region <pass> --dump <addr0> <addr1>` or
`netlist_slice.fmt_let()`.

Usage:  python modules_split.py
"""
import argparse
import collections
import importlib.util
import json
import os
import re
import sys

import netlist_slice as ns
from netlist_stream import Stream

PASSES = (("init", "init"), ("cycle2", "cycle0_stage3"))
OUTDIR = "research/modules"


def load_model():
    spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
    cosim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cosim)
    return cosim.Model("model/COSIM.m2630opt.Jul1599", "model/pin.list")


def block_of(name):
    if not name:
        return None
    p = name.split(".")
    if p and p[0] == "GKO" and len(p) >= 2:
        return p[1]
    return None


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--region", default="all",
                    choices=["all", "init", "cycle2"])
    ap.add_argument("--items-cap", type=int, default=100,
                    help="literals printed per clause before eliding")
    ap.add_argument("--budget", type=int, default=20000,
                    help="character budget per expression")
    ap.add_argument("--depth-cap", type=int, default=24,
                    help="nesting depth before a cone is elided")
    args = ap.parse_args()
    sys.setrecursionlimit(200000)

    m = load_model()
    names = m.slot_names
    s = Stream()
    d, _ = ns.load_trace()
    regvals = json.load(open("research/gt_regs.json"))

    passes = PASSES if args.region == "all" else \
        tuple(p for p in PASSES if p[0] == args.region)

    # ---- collect every statement, with its pass and block ----
    rows = []                    # (block, pass, addr, bank, slot, name, node,
                                 #  bmask)
    votes = collections.defaultdict(collections.Counter)
    sliced = []
    for region, table in passes:
        sl = ns.Slicer(s, {}, regvals=regvals.get(table))
        sl.run_pass(ns.order_for(d, region))
        sliced.append((region, sl))
        for st in sl.statements:
            a, b, slot, v, bmask, wsrc = ns.stmt_parts(st)
            blk = block_of(names.get(slot, ""))
            if blk:
                votes[a >> 12][blk] += 1
    bmap = {k: c.most_common(1)[0][0] for k, c in votes.items() if c}

    for region, sl in sliced:
        for st in sl.statements:
            a, b, slot, v, bmask, wsrc = ns.stmt_parts(st)
            nm = names.get(slot, "")
            blk = block_of(nm) or bmap.get(a >> 12) or "UNATTRIBUTED"
            rows.append((blk, region, a, b, slot, nm, v, bmask, wsrc))

    os.makedirs(args.outdir, exist_ok=True)
    per = collections.defaultdict(list)
    for r in rows:
        per[r[0]].append(r)

    total = len(rows)
    index = []
    for blk in sorted(per):
        rs = sorted(per[blk], key=lambda r: (r[2], r[1]))
        path = os.path.join(args.outdir, safe(blk) + ".txt")
        n_init = sum(1 for r in rs if r[1] == "init")
        n_cyc = len(rs) - n_init
        n_named = sum(1 for r in rs if r[5])
        n_word = sum(1 for r in rs if r[7] == 0)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# GKO module %s -- recovered 2-value netlist\n" % blk)
            f.write("# model: model/COSIM.m2630opt.Jul1599 (compiled PPC "
                    "netlist)\n")
            f.write("# statements: %d (init pass %d, per-cycle pass %d)\n"
                    % (len(rs), n_init, n_cyc))
            f.write("#   of which %d drive a named wire, %d are whole-word "
                    "copies\n" % (n_named, n_word))
            f.write("#\n# format: @<code addr>  b<bank>.<slot>  <signal name>"
                    "  <=  <expression>\n")
            f.write("#   b<bank>.<slot> : state wire; the 8 banks are the "
                    "L1/L2 planes of the\n#      two-value simulation\n")
            f.write("#   wN_MMMM        : the same wire read as an input\n")
            f.write("#   fK_ADDR        : value assembled by bit packing / "
                    "address arithmetic\n")
            f.write("#   mem_rN[d]      : byte read through a non-bank pointer"
                    " (array image)\n")
            f.write("#   in_rN          : value entering the fragment in "
                    "register rN\n")
            f.write("#   &  |  ^  ~     : boolean operators (negation pushed "
                    "to the literals)\n")
            f.write("#   <whole-word copy> : lwz->stw of a word never "
                    "modified in between\n")
            f.write("#   '... N more...' : a wide clause elided by the printer"
                    " (use --dump)\n")
            f.write("#\n")
            for blk2, region, a, b, slot, nm, v, bmask, wsrc in rs:
                if bmask == 0:
                    body = "<whole-word copy>"
                else:
                    body = ns.fmt(v, names, depth=0,
                                  max_items=args.items_cap,
                                  budget=[args.budget])
                f.write("@%08x  b%d.%04x  %-44s <= %s\n"
                        % (a, b, slot, nm, body))
        index.append((blk, len(rs), n_init, n_cyc, n_named, n_word, path))
        print("  %-14s %6d statements -> %s" % (blk, len(rs), path))

    with open(os.path.join(args.outdir, "README.md"), "w",
              encoding="utf-8") as f:
        f.write("# Recovered netlist split by original source module\n\n")
        f.write("The model's symbol table keeps the design hierarchy in the "
                "wire names\n(`GKO.<BLOCK>.<signal>…`), so every recovered "
                "statement is routed to the block\nwhose wire it drives; when "
                "the wire is a nameless local cone the block is\ntaken from "
                "the code region that executed it (the compiled code is laid "
                "out\nblock by block).\n\n")
        f.write("Total: **%d statements in %d modules** (init pass + "
                "per-cycle pass).\n\n" % (total, len(index)))
        f.write("| module | statements | init | per-cycle | named wires | "
                "whole-word copies |\n|---|---:|---:|---:|---:|---:|\n")
        for blk, n, ni, nc, nn, nw, path in sorted(index, key=lambda x: -x[1]):
            f.write("| [%s](%s) | %d | %d | %d | %d | %d |\n"
                    % (blk, os.path.basename(path), n, ni, nc, nn, nw))
        f.write("\nReproduce with `python modules_split.py`.\n")
        f.write("\nExpressions are printed with depth/width/length caps; a "
                "wide clause ends in\n`... N more...`.  For a faithful "
                "rendering of one statement use\n`python netlist_slice.py "
                "--region <pass> --dump <addr0> <addr1>`.\n")
    print("\n%d statements in %d module files -> %s"
          % (total, len(index), args.outdir))
    print("index: %s" % os.path.join(args.outdir, "README.md"))


if __name__ == "__main__":
    main()
