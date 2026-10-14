#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netlist_stream.py -- shared loader / model of the compiled netlist instruction
stream produced by `netlist_extract.py`.

Concepts
--------
* strand     : the whole code region as one sequence of 4-byte instruction
               words, in address order.  A logic element ("gene") is a
               *contiguous substring* of the strand.  Nothing is assumed
               about the 0x80-byte anchor grid: elements may straddle cells.
* anchor/nop : words that were patch-list nodes; at run time they are
               `0x60000000` (nop).  They are *introns*: they are executed
               (branches count them) but they never belong to a pattern.
* slot       : 16-bit state-wire id  = displacement & 0xFFFF, where the base
               register is one of the 8 state banks r13..r20.
* bank       : regA-13 for a bank-relative access.
* shape      : operand-normalised instruction key, so that two instances of
               the same logic element match even though their ports (register
               numbers, wire offsets, polarity) differ.
"""
import struct

REC = struct.Struct(">IBIIIIIHBB")
REC_SIZE = REC.size
N_REC_FIELDS = 10                 # struct drops the trailing pad byte
# record field indices
F_ADDR, F_TKN, F_RAW = 0, 1, 2
F_F0, F_F1, F_F2 = 3, 4, 5
F_RG, F_SLO, F_FLG = 6, 7, 8

F_PATCH = 1
F_BANK = 2
F_UNKNOWN = 4
F_MEM = 8

REGION_INIT = (0x2C, 0x1BCD60)
REGION_CYCLE1 = (0x1BCD60, 0x2341C8)
REGION_CYCLE2 = (0x2341CC, 0x4BA840)

# mnemonics whose last operand is a literal that must stay in the shape key
# (it participates in the *function*, not only in the port numbering)
FUNC_LITERAL = {
    "rlwimi": ("sh", "mb", "me"), "rlwinm": ("sh", "mb", "me"),
    "rlwnm": ("sh", "mb", "me"), "slwi": ("sh",), "srwi": ("sh",),
    "srawi": ("sh",), "extlwi": ("sh", "n"), "extrwi": ("sh", "n"),
    "clrlwi": ("n",), "rotlwi": ("sh",),
    "ori": ("u",), "oris": ("u",), "xori": ("u",), "xoris": ("u",),
    "and.": (), "or.": (), "xor.": (), "addi": ("s",), "addis": ("s",),
}


class Stream(object):
    def __init__(self, path="research/netlist_ins.bin"):
        with open(path, "rb") as f:
            blob = f.read()
        off = 0
        (ntok,) = struct.unpack_from(">I", blob, off)
        off += 4
        mon = []
        for _ in range(ntok):
            (ln,) = struct.unpack_from(">B", blob, off)
            off += 1
            mon.append(blob[off:off + ln].decode("latin1"))
            off += ln
        (n,) = struct.unpack_from(">I", blob, off)
        off += 4
        self.mon = mon
        self.n = n
        self.recs = [REC.unpack_from(blob, off + i * REC_SIZE)
                     for i in range(n)]
        self.addr2i = {r[0]: i for i, r in enumerate(self.recs)}
        self.NOP = mon.index("nop")
        # convenience views
        self.mn = [mon[r[1]] for r in self.recs]
        self.is_nop = [r[1] == self.NOP for r in self.recs]
        self.slot = [r[F_SLO] for r in self.recs]
        self.bank = [((r[F_RG] >> 8) & 0xFF) - 13 if (r[F_FLG] & F_BANK)
                     else -1 for r in self.recs]
        self.flags = [r[F_FLG] for r in self.recs]
        self.f0 = [r[F_F0] for r in self.recs]
        self.f1 = [r[F_F1] for r in self.recs]
        self.f2 = [r[F_F2] for r in self.recs]
        # non-nop positions (the "exon" index)
        self.pos = [i for i in range(n) if not self.is_nop[i]]
        self.index_of_pos = {p: k for k, p in enumerate(self.pos)}

    # ------------------------------------------------------------------
    def regs(self, i):
        """(rt, ra, rb) -- canonical PPC fields from the encoding.

        rt = bits 6..10   (rS/rD: source for the X-form logic ops,
                           destination for addi/ori/lis and the load target)
        ra = bits 11..15  (rA: base register for memory ops)
        rb = bits 16..20  (rB: second source; for the X-form logic ops
                           `or rA, rS, rB` the *destination* is encoded here)
        """
        rg = self.recs[i][F_RG]
        return (rg & 0xFF, (rg >> 8) & 0xFF, (rg >> 16) & 0xFF)

    def text(self, i, names=None):
        """human-readable instruction; names: slot -> signal name"""
        r = self.recs[i]
        a, t, raw, f0, f1, f2 = r[0], r[1], r[2], r[3], r[4], r[5]
        rg, slot, flags = r[F_RG], r[F_SLO], r[F_FLG]
        mn = self.mon[t]
        rs, ra, rb = self.regs(i)
        if flags & F_PATCH:
            return "nop [anchor]"
        if mn in ("lbz", "lhz", "lha", "lwz", "lmw", "stb", "sth", "stw",
                  "stmw", "lbzu", "lwzu"):
            sd = f0 - 0x100000000 if f0 & 0x80000000 else f0
            ann = ""
            if flags & F_BANK:
                nm = names.get(slot, "") if names else ""
                ann = "  ; slot %04x %s" % (slot, nm)
            return "%s r%d, %d(r%d)%s" % (mn, rs, sd, ra, ann)
        if mn in ("beq", "bne", "bc", "b", "bl", "bdnz"):
            return "%s 0x%x" % (mn, f2)
        if mn in ("and", "andc", "or", "orc", "nor", "nand", "xor", "eqv",
                  "add", "subfc"):
            return "%s r%d, r%d, r%d" % (mn, ra, rs, rb)
        if mn in ("rlwinm", "rlwimi", "rlwnm"):
            return "%s r%d, r%d, %d, %d, %d" % (mn, ra, rs, f0, f1, f2)
        if mn in ("addi", "addis", "ori", "oris", "xori", "xoris", "mulli"):
            sd = f0 - 0x100000000 if f0 & 0x80000000 else f0
            imm = f0 if mn in ("ori", "oris", "xori", "xoris") else sd
            return "%s r%d, r%d, %d" % (mn, rs, ra, imm)
        if mn in ("cmplwi", "cmpwi"):
            return "%s r%d, %d" % (mn, ra, f0)
        if mn in ("cmplw", "cmpw"):
            return "%s r%d, r%d" % (mn, ra, rb)
        if mn in ("mtlr", "mflr"):
            return "%s r%d" % (mn, rs)
        if mn == "mr":
            return "mr r%d, r%d" % (ra, rs)
        return mn

    # ------------------------------------------------------------------
    def shape(self, i, use_regs=True, use_lits=True):
        """operand-normalised key for one instruction.

        Register numbers are replaced by the *definition index* of the
        register inside the window when available, so that the data flow is
        preserved while port numbering is abstracted away.
        """
        r = self.recs[i]
        a, t, raw, f0, f1, f2 = r[0], r[1], r[2], r[3], r[4], r[5]
        rg, slot, flags = r[F_RG], r[F_SLO], r[F_FLG]
        mn = self.mon[t]
        if flags & F_PATCH:
            return None
        rs, ra, rb = self.regs(i)
        parts = [mn]
        if mn in ("and", "andc", "or", "orc", "nor", "nand", "xor", "eqv",
                  "add", "subfc"):
            parts.append("r%d<-%d,%d" % (ra, rs, rb))
        elif mn in ("lbz", "lhz", "lha", "lwz", "lmw", "stb", "sth", "stw",
                    "stmw"):
            if flags & F_BANK:
                parts.append("b%d[%d]->r%d" % (self.bank[i], slot, rs))
            else:
                parts.append("r%d->r%d" % (ra, rs))
        elif mn in ("rlwinm", "rlwimi", "rlwnm"):
            parts.append("%d,%d,%d" % (f0, f1, f2))
        elif mn in ("ori", "oris", "xori", "xoris"):
            parts.append("%d" % f0)
        elif mn in ("addi", "addis", "mulli", "cmplwi", "cmpwi"):
            parts.append("imm")
        elif mn in ("beq", "bne", "bc", "bdnz"):
            parts.append("bo%d" % f0)
        elif mn in ("b", "bl"):
            parts.append("tgt")
        elif mn in ("mtlr", "mflr"):
            parts.append("r%d" % rs)
        return " ".join(parts)
