#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macroblocks.py -- identify the macroblocks (compiled logic elements) of the
GKO model.

A "macroblock" is the instruction template the compiler emits for one logic
element of the original schematic.  It is recovered like this:

  1. replay the *executed* instruction stream in execution order (ground truth
     from cosim.py, so dead code, patch anchors and not-taken branches never
     contribute);
  2. for every instruction remember the instruction that defined each source
     register (a def-use chain over registers);
  3. for every store to a state wire, walk that chain backwards and collect
     the *template* of the value being stored: the mnemonic sequence of the
     instructions that produced it, in data-flow order, with
     - memory accesses collapsed to `ld(bank)` / `ld(ptr)` / `st(bank)`
       (their offsets and register numbers are the element's *parameters*,
       and must not take part in the pattern),
     - the rotate/shift/compare constants kept (they change the function);
  4. group the templates: identical templates are one macroblock family;
     report the family sizes, the parameter variability inside each family
     (how many distinct slot offsets / registers it appears with) and the code
     addresses of representative instances.

Usage:
    python3 macroblocks.py --top 40
    python3 macroblocks.py --show 4            # instances of family #4
    python3 macroblocks.py --emit research/macroblocks.txt
"""
import argparse
import collections
import importlib.util
import json
import sys

from netlist_stream import Stream

LOGIC = {"and", "andc", "or", "orc", "nor", "nand", "xor", "eqv"}
LOADS = {"lbz", "lhz", "lha", "lwz", "lmw", "lbzu", "lwzu"}
STORES = {"stb", "sth", "stw", "stmw", "stbu", "sthu", "stwu"}
ROTS = {"rlwinm", "rlwimi", "rlwnm", "slwi", "srwi", "clrlwi", "extlwi",
        "extrwi", "rotlwi"}
IMM = {"addi", "addis", "ori", "oris", "xori", "xoris", "mulli"}
CMP = {"cmplwi", "cmpwi", "cmplw", "cmpw"}
BRANCH = {"beq", "bne", "b", "bc", "bdnz", "blr", "blrl", "bl", "mtlr",
          "mflr"}


class DefUse(object):
    """def-use chain over registers for one executed pass"""

    def __init__(self, s):
        self.s = s
        self.defs = {}         # reg -> defining instruction address
        self.tmpl = []        # per store: (addr, bank, slot, template, params)

    def run(self, addrs):
        s = self.s
        for a in addrs:
            i = s.addr2i.get(a)
            if i is None:
                continue
            mn = s.mn[i]
            rt, ra, rb = s.regs(i)
            if mn in LOADS:
                self.defs[rt] = a
            elif mn in LOGIC:
                self.defs[rt] = a
            elif mn in IMM or mn in ROTS:
                self.defs[rt] = a
            elif mn == "mr":
                self.defs[rt] = self.defs.get(ra, a)
            elif mn in ("li", "lis", "add", "subfc"):
                self.defs[rt] = a
            elif mn in STORES:
                if s.bank[i] >= 0:
                    tpl, params = self.template(a, rt)
                    self.tmpl.append((a, s.bank[i], s.slot[i], tpl, params))
        return self.tmpl

    # ------------------------------------------------------------------
    def srcs(self, i):
        """source registers of instruction i that feed its result"""
        s = self.s
        mn = s.mn[i]
        rt, ra, rb = s.regs(i)
        if mn in LOADS:
            return [ra] if ra not in range(13, 21) else []
        if mn in LOGIC:
            return [ra, rb]
        if mn in IMM or mn in ROTS:
            return [ra]
        if mn == "mr":
            return [ra]
        return []

    def node_key(self, i):
        """pattern token of one instruction: operands abstracted away except
        the literals that change the boolean function"""
        s = self.s
        mn = s.mn[i]
        r = s.recs[i]
        f0, f1, f2 = r[3], r[4], r[5]
        if mn in LOADS:
            return "ld(bank)" if s.bank[i] >= 0 else "ld(mem)"
        if mn in STORES:
            return "st(bank)" if s.bank[i] >= 0 else "st(mem)"
        if mn in ROTS:
            return "%s(%d,%d,%d)" % (mn, f0, f1, f2)
        if mn == "ori":
            return "ori"
        if mn in IMM:
            return mn
        if mn in CMP:
            return mn
        return mn

    def template(self, addr, reg, limit=64):
        """instruction template of the value in `reg` at `addr`, in data-flow
        order; also returns the observed parameters (slots, registers)."""
        s = self.s
        seq = []
        params = []
        seen = set()
        stack = [reg]
        visited = set()
        while stack:
            rg = stack.pop()
            d = self.defs.get(rg)
            if d is None or d in visited or d >= addr:
                continue
            visited.add(d)
            i = s.addr2i.get(d)
            if i is None:
                continue
            seq.append((d, i))
            if s.bank[i] >= 0:
                params.append(("slot", s.slot[i]))
            elif s.mn[i] in LOADS:
                params.append(("reg", s.regs(i)[1]))
            for src in self.srcs(i):
                stack.append(src)
        seq.sort(key=lambda t: t[0])
        # keep the last occurrence of each mnemonic-bearing node: the chain may
        # contain several definitions of one register; keep the nearest one
        tpl = tuple(self.node_key(i) for a, i in seq)
        return tpl, params


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--show", type=int, default=None,
                    help="dump instance details of family number N")
    ap.add_argument("--emit", default=None, help="write the catalog to a file")
    ap.add_argument("--region", default="all",
                    choices=["all", "init", "cycle1", "cycle2"])
    args = ap.parse_args()

    s = Stream()
    # ground truth from gt_dump.py: executed addresses plus the interpreter's
    # exact execution order (sorting addresses is not execution order once the
    # netlist loops back)
    import netlist_slice as ns
    d, _ = ns.load_trace("research/gt_exec.json")
    if args.region == "all":
        addrs = (ns.order_for(d, "init") + ns.order_for(d, "cycle1") +
                 ns.order_for(d, "cycle2"))
    else:
        addrs = ns.order_for(d, args.region)
    print("executed instructions in region '%s': %d" % (args.region,
                                                         len(addrs)))

    du = DefUse(s)
    stores = du.run(addrs)
    print("bank stores (state wires written): %d" % len(stores))

    fam = collections.Counter()
    fam_ex = {}
    fam_params = collections.defaultdict(set)
    for a, bank, slot, tpl, params in stores:
        fam[tpl] += 1
        fam_ex.setdefault(tpl, (a, bank, slot, params))
        # parameters: which slots/registers this family is instantiated with
        for kind, val in params:
            fam_params[tpl].add((kind, val))

    total = sum(fam.values())
    print("distinct macroblock templates: %d" % len(fam))
    print("\n%-6s %8s %8s  %s" % ("#", "count", "params", "template"))
    lines = []
    for n, (tpl, c) in enumerate(fam.most_common(args.top)):
        a, bank, slot, params = fam_ex[tpl]
        t = " ".join(tpl) if tpl else "(const/load only)"
        print("%-6d %8d %8d  %s" % (n, c, len(fam_params[tpl]), t[:100]))
        lines.append((n, c, tpl, len(fam_params[tpl])))

    if args.emit:
        with open(args.emit, "w", encoding="utf-8") as f:
            f.write("# macroblock templates of %s (region %s)\n"
                    % ("model/COSIM.m2630opt.Jul1599", args.region))
            f.write("# count\tparam_count\ttemplate\n")
            for tpl, c in fam.most_common():
                t = " ".join(tpl) if tpl else "(const)"
                f.write("%d\t%d\t%s\n" % (c, len(fam_params[tpl]), t))
        print("\nwritten", args.emit)

    if args.show is not None:
        tpl, c = fam.most_common(args.show)[0]
        print("\n== family #%d (%d instances) ==" % (args.show, c))
        print("template:", " ".join(tpl))
        shown = 0
        for a, bank, slot, t, params in stores:
            if t != tpl:
                continue
            print("  @%08x  b%d.%04x  params=%s" % (a, bank, slot, params))
            shown += 1
            if shown >= 12:
                break


if __name__ == "__main__":
    main()
