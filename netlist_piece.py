#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
piece_netlist.py -- turn the executed straight-line code into netlist
statements (assignments / gates), then summarise the statement structure.

For every linear piece of executed code (a maximal run of physically
consecutive executed instructions) the registers are tracked symbolically:

    R[rt] = expression over
              ('slot', bank, slot)        a state wire read through a bank
              ('ptr',  <reg>, <addr>)     a byte read through another base
                                          (array/memory image -- opaque)
              ('ext',  <reg>)             a value that entered the piece
                                          in a register (opaque input)
              ('not'|'and'|'or'|'xor'|..., args)
              ('const', v)

On a store the statement `dst_slot <= expression` is emitted.  That is the
netlist, recovered: the gates of the original schematic appear as the
expression trees.

Usage:
    python3 piece_netlist.py --list 0x382c00 20
    python3 piece_netlist.py --stats
"""
import argparse
import collections
import json
import sys

from netlist_stream import Stream, F_BANK

BANKS = range(13, 21)


class Piece(object):
    def __init__(self, s, addrs):
        self.s = s
        self.addrs = addrs
        self.stmts = []          # (addr, kind, dst, expr)
        self.defsite = {}        # reg -> address of its definition
        self.expr = {}           # reg -> expression
        self.regbase = {}        # reg -> ('BANK', k) | ('PTR', addr0)
        for b in BANKS:
            self.regbase[b] = ('BANK', b - 13)
        self.run()

    # ---- expression helpers -------------------------------------------
    @staticmethod
    def simp(e):
        t = e[0]
        if t == 'not':
            a = Piece.simp(e[1])
            if a[0] == 'const':
                return ('const', 1 - a[1])
            if a[0] == 'not':
                return a[1]
            return ('not', a)
        if t in ('and', 'or', 'xor', 'andc', 'orc', 'nand', 'nor', 'eqv'):
            a, b = Piece.simp(e[1]), Piece.simp(e[2])
            if a[0] == 'const' and b[0] == 'const':
                x, y = a[1], b[1]
                v = {'and': x & y, 'or': x | y, 'xor': x ^ y,
                     'andc': x & (1 - y), 'orc': x | (1 - y),
                     'nand': 1 - (x & y), 'nor': 1 - (x | y),
                     'eqv': 1 - (x ^ y)}[t]
                return ('const', v)
            # canonical operand order
            if repr(a) > repr(b):
                a, b = b, a
                if t in ('andc', 'orc'):
                    return (t, a, b)      # not commutative
            if a == b:
                if t in ('and', 'or'):
                    return a
                if t == 'xor':
                    return ('const', 0)
                if t == 'eqv':
                    return ('const', 1)
            return (t, a, b)
        return e

    @staticmethod
    def fmt(e, names=None):
        t = e[0]
        if t == 'slot':
            nm = names.get(e[2], "") if names else ""
            return "b%d.%04x%s" % (e[1], e[2], ("[" + nm + "]") if nm else "")
        if t == 'ptr':
            return "ptr%d[%d]" % (e[1], e[2])
        if t == 'ext':
            return "in_r%d" % e[1]
        if t == 'const':
            return str(e[1])
        if t == 'not':
            return "~%s" % Piece.fmt(e[1], names)
        opsym = {'and': '&', 'or': '|', 'xor': '^', 'andc': '&~',
                 'orc': '|~', 'nand': '~&', 'nor': '~|', 'eqv': '='}
        return "(%s %s %s)" % (Piece.fmt(e[1], names),
                               opsym.get(t, t), Piece.fmt(e[2], names))

    # ---- interpretation ------------------------------------------------
    def run(self):
        s = self.s
        for a in self.addrs:
            i = s.addr2i[a]
            mn = s.mn[i]
            rt, ra, rb = s.regs(i)
            flags = s.recs[i][8]
            f0 = s.recs[i][3]
            if mn in ("lbz", "lhz", "lha", "lwz", "lmw", "lbzu", "lwzu"):
                if flags & F_BANK:
                    self.expr[rt] = ('slot', s.bank[i], s.slot[i])
                else:
                    base = self.regbase.get(ra, ('EXT', ra))
                    self.expr[rt] = ('ptr', ra, f0)
                self.defsite[rt] = a
            elif mn in ("stb", "sth", "stw", "stmw", "stbu", "sthu", "stwu"):
                v = self.expr.get(rt, ('ext', rt))
                if flags & F_BANK:
                    self.stmts.append((a, s.slot[i], s.bank[i], v))
                self.expr.pop(rt, None)
            elif mn in ("and", "andc", "or", "orc", "nor", "nand", "xor",
                        "eqv", "add", "subfc"):
                x = self.expr.get(rt, ('ext', rt))
                y = self.expr.get(rb, ('ext', rb))
                table = {'and': 'and', 'andc': 'andc', 'or': 'or',
                         'orc': 'orc', 'nor': 'nor', 'nand': 'nand',
                         'xor': 'xor', 'eqv': 'eqv', 'add': 'add',
                         'subfc': 'sub'}
                self.expr[rb] = self.simp((table[mn], x, y))
                self.defsite[rb] = a
            elif mn in ("addi",):
                sd = f0 - 0x100000000 if f0 & 0x80000000 else f0
                v = self.expr.get(ra)
                if v is not None and v[0] == 'const':
                    self.expr[rt] = ('const', (v[1] + sd) & 0xFFFFFFFF)
                elif sd == 0 and v is not None:
                    self.expr[rt] = v
                else:
                    self.expr[rt] = ('addr', ra, sd)
            elif mn in ("addis",):
                sd = f0 - 0x100000000 if f0 & 0x80000000 else f0
                self.expr[rt] = ('addr', ra, sd << 16)
                self.regbase[rt] = ('PTR',)
            elif mn in ("lis", "li"):
                sd = f0 - 0x100000000 if f0 & 0x80000000 else f0
                self.expr[rt] = ('const', (sd << 16) & 0xFFFFFFFF if mn == 'lis' else sd)
            elif mn in ("ori", "oris", "xori", "xoris"):
                v = self.expr.get(ra)
                iv = f0 if mn in ('ori', 'xori') else (f0 << 16)
                if v is not None and v[0] == 'const':
                    nv = (v[1] | iv) if mn in ('ori', 'oris') else (v[1] ^ iv)
                    self.expr[rt] = ('const', nv & 0xFFFFFFFF)
                else:
                    self.expr[rt] = ('ext', rt)
            elif mn == "mr":
                self.expr[rt] = self.expr.get(ra, ('ext', ra))
                self.defsite[rt] = a
            elif mn in ("slwi", "rlwinm", "rlwimi", "srwi", "clrlwi",
                        "extlwi", "extrwi", "rlwnm"):
                self.expr[rt] = ('bitfield', mn, f0, self.s.recs[i][4],
                                 self.s.recs[i][5])
                self.defsite[rt] = a
            elif mn == "mulli":
                self.expr[rt] = ('mul', ra, f0)
            elif mn in ("cmplwi", "cmpwi", "cmplw", "cmpw"):
                pass
            elif mn in ("beq", "bne", "b", "bc", "bdnz", "blr", "blrl",
                        "mtlr", "mflr", "bl"):
                pass
            else:
                self.expr[rt] = ('ext', rt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", nargs=2, default=None,
                    metavar=("ADDR", "N"), help="dump pieces around ADDR")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--region", default="cycle2")
    args = ap.parse_args()

    s = Stream()
    gt = json.load(open("research/netlist_gt.json"))
    ex = set(int(k, 16) for k in gt["exec_cnt"])
    if args.region == "init":
        ex = set(a for a in ex if a < 0x1BCD60)
    elif args.region == "cycle1":
        ex = set(a for a in ex if 0x1BCD60 <= a < 0x2341C8)
    elif args.region == "cycle2":
        ex = set(a for a in ex if a >= 0x2341CC)
    addrs = sorted(ex)
    pieces = []
    cur = []
    for a in addrs:
        if cur and (a != cur[-1] + 4):
            pieces.append(cur)
            cur = []
        cur.append(a)
    if cur:
        pieces.append(cur)
    print("pieces:", len(pieces))

    names = {}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
        cosim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cosim)
        names = cosim.Model("model/COSIM.m2630opt.Jul1599",
                            "model/pin.list").slot_names
    except Exception as e:
        print("(no names: %s)" % e)

    if args.list:
        target = int(args.list[0], 0)
        want = []
        for p in pieces:
            if p[0] <= target <= p[-1] + 4 or abs(p[0] - target) < 0x400:
                want.append(p)
            if len(want) >= int(args.list[1]):
                break
        for p in want:
            pc = Piece(s, p)
            print("\n--- piece 0x%x..0x%x (%d ins) ---"
                  % (p[0], p[-1], len(p)))
            for a, slot, bank, v in pc.stmts:
                print("  @%08x  b%d.%04x <= %s" % (a, bank, slot,
                                                   Piece.fmt(v, names)))
        return

    # statistics over all pieces
    opcnt = collections.Counter()
    nstmt = 0
    multi = 0
    for p in pieces:
        pc = Piece(s, p)
        for a, slot, bank, v in pc.stmts:
            nstmt += 1
            def count_ops(e):
                if e[0] in ('and', 'or', 'xor', 'andc', 'orc', 'nand',
                            'nor', 'eqv'):
                    opcnt[e[0]] += 1
                    count_ops(e[1])
                    count_ops(e[2])
                elif e[0] == 'not':
                    opcnt['not'] += 1
                    count_ops(e[1])
            count_ops(v)
    print("statements: %d" % nstmt)
    for k, v in opcnt.most_common():
        print("  %-6s %d" % (k, v))


if __name__ == "__main__":
    main()
