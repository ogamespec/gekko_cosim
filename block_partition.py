#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
block_partition.py -- split the recovered netlist into the original source
modules, and measure its coverage.

Two facts make the split possible without guessing:

  * the model's symbol table keeps the design hierarchy in the wire names:
    `GKO.<BLOCK>.<signal>.<...>` -- 85 top-level blocks, the `*.dsl` source
    files the issue mentions;
  * every statement writes a state wire, so it belongs to the block named by
    that wire; statements whose destination slot has no name are attributed by
    the code region they were executed from (`research/GKO_CODE_MAP.md` is the
    same idea computed independently, for comparison).

Coverage is reported against the set of slots the model *does* drive at run
time (any bank store in the executed trace), so it answers "is this the whole
netlist or is some of it missing", not just "how many names exist".

Usage:
    python block_partition.py
    python block_partition.py --emit research/netlist_by_block.txt
"""
import argparse
import collections
import importlib.util
import json
import sys

import netlist_slice as ns
from netlist_stream import Stream


def model():
    spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
    cosim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cosim)
    return cosim, cosim.Model("model/COSIM.m2630opt.Jul1599", "model/pin.list")


def block_of(name):
    """top-level block of a symbol-table name"""
    if not name:
        return None
    p = name.split(".")
    if p and p[0] == "GKO" and len(p) >= 2:
        return p[1]
    return None


def bucket_map(s, d, names, regvals, tab):
    """dominant block per 4 KiB code bucket.

    Most wires written by the model have no symbol-table name (they are local
    cones), so a name alone cannot attribute their statements.  The compiled
    code is laid out block by block, so the *code address* carries the
    attribution: for every 4 KiB bucket take the block that dominates the
    named destinations of the statements executed from it."""
    votes = collections.defaultdict(collections.Counter)
    for r in ("init", "cycle1", "cycle2"):
        sl = ns.Slicer(s, {}, regvals=regvals.get(tab[r]))
        sl.run_pass(ns.order_for(d, r))
        for st in sl.statements:
            a, b, slot, v, bmask, wsrc = ns.stmt_parts(st)
            blk = block_of(names.get(slot, ""))
            if blk:
                votes[a >> 12][blk] += 1
    return {k: c.most_common(1)[0][0] for k, c in votes.items() if c}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", default=None)
    ap.add_argument("--expr-cap", type=int, default=600,
                    help="emit: truncate each expression to this many chars")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    sys.setrecursionlimit(200000)

    cosim, m = model()
    names = m.slot_names
    s = Stream()
    d, _ = ns.load_trace()
    regs = json.load(open("research/gt_regs.json"))
    tab = {"init": "init", "cycle1": "cycle0_stage1", "cycle2": "cycle0_stage3"}

    # ---- everything the model actually drives, from the executed trace ----
    driven = collections.defaultdict(set)      # (bank,slot) -> {passes}
    store_addr = set()
    for r in ("init", "cycle1", "cycle2"):
        for a in ns.order_for(d, r):
            i = s.addr2i.get(a)
            if i is None:
                continue
            if s.mn[i] in ("stb", "stw", "sth", "stmw") and s.bank[i] >= 0:
                driven[(s.bank[i], s.slot[i])].add(r)
                store_addr.add(a)

    # ---- statements recovered, attributed to a block ----
    bmap = bucket_map(s, d, names, regs, tab)
    per_block = collections.Counter()
    per_block_pass = collections.defaultdict(collections.Counter)
    by_name = by_code = 0
    allstmts = []
    for r in ("init", "cycle1", "cycle2"):
        sl = ns.Slicer(s, {}, regvals=regs.get(tab[r]))
        sl.run_pass(ns.order_for(d, r))
        for st in sl.statements:
            a, b, slot, v, bmask, wsrc = ns.stmt_parts(st)
            nm = names.get(slot, "")
            blk = block_of(nm)
            if blk:
                by_name += 1
            else:
                blk = bmap.get(a >> 12)
                if blk:
                    by_code += 1
            blk = blk or "(unattributed)"
            per_block[blk] += 1
            per_block_pass[blk][r] += 1
            allstmts.append((blk, r, a, b, slot, nm, v, bmask))

    total = sum(per_block.values())
    print("recovered statements: %d" % total)
    print("bank stores in the executed trace: %d over %d distinct (bank,slot)"
          % (len(store_addr), len(driven)))
    print("statements recovered / stores executed: %.1f %%"
          % (100.0 * total / max(1, len(store_addr))))
    print("attribution: %d by wire name, %d by code address, %d unattributed"
          % (by_name, by_code, per_block["(unattributed)"]))
    print()
    print("%-14s %9s %8s %9s %9s"
          % ("block", "stmts", "share", "init", "cycle2"))
    for blk, c in per_block.most_common(args.top):
        np_ = per_block_pass[blk]
        print("%-14s %9d %7.1f%% %9d %9d" %
              (blk, c, 100.0 * c / total, np_["init"], np_["cycle2"]))

    # ---- coverage of the wires the model drives ----
    rec = set()
    for blk, r, a, b, slot, nm, v, bmask in allstmts:
        rec.add((b, slot))
    miss = set(driven) - rec
    named_driven = [k for k in driven if names.get(k[1])]
    print()
    print("wires the model drives: %d (%d with a symbol name)"
          % (len(driven), len(named_driven)))
    print("wires covered by the recovered netlist: %d (%.1f %%)"
          % (len(rec & set(driven)),
             100.0 * len(rec & set(driven)) / max(1, len(driven))))
    print("driven wires NOT recovered: %d" % len(miss))
    bm = collections.Counter()
    for (b, slot) in miss:
        bm[block_of(names.get(slot, "")) or "(unresolved)"] += 1
    print("  by block:", bm.most_common(10))

    # ---- blocks present in the symbol table but never driven ----
    names_driven = set(names[slot] for (b, slot) in driven if slot in names
                       and names[slot])
    nblk = collections.Counter()
    for (b, slot) in driven:
        nm = names.get(slot, "")
        blk = block_of(nm)
        if blk:
            nblk[blk] += 1
    all_blocks = set(block_of(v) for v in names.values() if block_of(v))
    print()
    print("top-level blocks in the symbol table: %d" % len(all_blocks))
    print("blocks with at least one driven wire: %d" % len(nblk))
    print("blocks with NO driven wire: %d" % len(all_blocks - set(nblk)))
    print("  ", sorted(all_blocks - set(nblk))[:20])

    if args.emit:
        # An *index* by module: the driver addresses and wires, without
        # re-printing the expressions.  That is deliberate -- the init pass's
        # megacones take hours to format, and the full expressions are already
        # in the per-cycle netlist file (research/netlist_recovered_cycle2.txt)
        # which the addresses here point into.
        byb = collections.defaultdict(list)
        for row in allstmts:
            byb[row[0]].append(row)
        with open(args.emit, "w", encoding="utf-8") as f:
            f.write("# Recovered netlist indexed by original source module "
                    "(block)\n")
            f.write("# statement routed by the wire's symbol name, else by the "
                    "code region\n# it executed from (the code is laid out "
                    "block by block)\n")
            f.write("# one line per statement: @code_addr  b<bank>.<slot>  "
                    "<signal name>\n")
            f.write("# The expressions of the per-cycle statements (6,680) are "
                    "in\n#   research/netlist_recovered_cycle2.txt\n")
            f.write("# The init-pass expressions are not written out by "
                    "default: their cones\n# reach thousands of nodes.  "
                    "Generate them with\n#   python netlist_slice.py --region "
                    "init --emit <file>\n")
            f.write("# total statements: %d across %d blocks\n"
                    % (total, len(byb)))
            for blk in sorted(byb, key=lambda b: -len(byb[b])):
                f.write("\n" + "#" * 72 + "\n# BLOCK %s  (%d statements, "
                        "init %d, cycle2 %d)\n"
                        % (blk, len(byb[blk]), per_block_pass[blk]["init"],
                           per_block_pass[blk]["cycle2"]) + "#" * 72 + "\n")
                for blk2, r, a, b, slot, nm, v, bmask in byb[blk]:
                    f.write("@%08x  b%d.%04x  %s%s\n"
                            % (a, b, slot, nm,
                               "   [whole-word copy]" if bmask == 0 else ""))
        print("\nwritten", args.emit)


if __name__ == "__main__":
    main()
