#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netlist_slice.py -- reconstruct the compiled netlist as gate statements.

The executed instruction stream is replayed in exact execution order (ground
truth from `netlist_gt.py`, which instruments the cosim.py interpreter).  For
every instruction the registers hold a symbolic value:

    slot(bank, id)      a state wire read through a state bank r13..r20
    mem(reg, disp)      a byte read through another base (memory image: array
                        data, ROM contents -- opaque to the logic)
    ext(reg)            a value inherited from outside the executed stream
    const(v)
    gate(op, args...)   and / or / xor / nor / nand / eqv / andc / orc / not
    bf(...)             a multi-bit field pack (rlwimi vector assembly)
    addr(...)           address arithmetic

Every store through a bank emits one statement

    <dst slot>  <=  <expression>

which *is* the netlist: the boolean structure of each state wire.  The
expression grammar is kept associative/commutative-normalised (AND and OR are
n-ary sets, negation is pushed to the leaves), so structurally identical
instances of one logic element hash to the same key.

Outputs:
    research/netlist_stmts.txt   readable statements (option --dump)
    research/gate_families.txt   macroblock families + instance counts

Usage:
    python3 netlist_slice.py --stats
    python3 netlist_slice.py --dump 0x3804c4 0x380600
    python3 netlist_slice.py --families
"""
import argparse
import collections
import importlib.util
import json
import sys

from netlist_stream import Stream

MODEL_PATH = "model/COSIM.m2630opt.Jul1599"

# ---------------------------------------------------------------------------
# expression model
#   atom      := ('s', bank, id) | ('p', reg, disp) | ('x', reg) | ('c', v)
#   literal   := (sign, atom)          sign 0 = positive, 1 = inverted
#   node      := literal | ('&', frozenset(literals)) | ('|', frozenset(literals))
# ---------------------------------------------------------------------------
XOR = '^'
AND, OR = '&', '|'


def lit(sign, atom):
    return (sign & 1, atom)


def is_clause(n):
    """(op, frozenset(literals), parity?)

    op is '&' (AND, n-ary), '|' (OR, n-ary) or '^' (XOR, n-ary); the optional
    third element is the XOR parity (0/1).  A literal is (sign, atom) with an
    integer sign, so clause and literal shapes can never be confused."""
    return (isinstance(n, tuple) and len(n) >= 2 and n[0] in (AND, OR, XOR))


def clause_lits(n):
    return n[1]


def clause_parity(n):
    return n[2] if len(n) > 2 else 0


def neg(n):
    """structural negation (De Morgan normal form)"""
    if is_clause(n):
        op = n[0]
        if op == XOR:
            return (XOR, n[1], 1 - clause_parity(n))
        inv = OR if op == AND else AND
        return (inv, frozenset((1 - s, a) for s, a in n[1]))
    s, a = n
    return (1 - s, a)


def is_const_atom(a):
    return isinstance(a, tuple) and len(a) == 2 and a[0] == 'c'


def mk(op, items):
    """build an AND/OR/XOR clause from nodes, flattening and absorbing.

    AND and OR are associative/commutative; XOR additionally carries a parity
    bit, and `x ^ x` cancels."""
    lits = set()
    konst = None
    parity = 0
    for it in items:
        if is_clause(it):
            if it[0] == op:
                # same operator: flatten
                if op == XOR:
                    parity ^= clause_parity(it)
                for x in clause_lits(it):
                    if x[1][0] == 'c':
                        konst = x[1][1] if x[0] == 0 else 1 - x[1][1]
                    else:
                        lits.add(x)
            else:
                lits.add(lit(0, it))
        else:
            if is_const_atom(it[1]):
                konst = it[1][1] if it[0] == 0 else 1 - it[1][1]
            else:
                lits.add(it)
    if op == XOR and konst is not None:
        parity ^= konst
        konst = None
    # constant absorption (AND / OR only)
    if konst is not None:
        if op == AND and konst == 0:
            return lit(0, ('c', 0))
        if op == OR and konst == 1:
            return lit(0, ('c', 1))
    # x & ~x -> 0 ; x | ~x -> 1 ; x ^ x -> 0
    for x in list(lits):
        if not (isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], int)):
            raise TypeError("bad literal %r (items=%r)" % (x, items))
        s, a = x
        if op == XOR:
            if (1 - s, a) in lits:
                lits.discard(x)
                lits.discard((1 - s, a))
                parity ^= 1
        elif (1 - s, a) in lits:
            return lit(0, ('c', 0 if op == AND else 1))
    if not lits:
        if op == XOR:
            return lit(0, ('c', parity))
        if konst is not None:
            return lit(0, ('c', konst))
        return lit(0, ('c', 1 if op == AND else 0))
    if len(lits) == 1 and op != XOR:
        only = next(iter(lits))
        if konst is None:
            return only
        if op == AND and konst == 1:
            return only
        if op == OR and konst == 0:
            return only
        return lit(0, ('c', 0 if op == AND else 1))
    if op == XOR:
        if len(lits) == 1:
            only = next(iter(lits))
            return only if parity == 0 else neg(only)
        return (XOR, frozenset(lits), parity)
    return (op, frozenset(lits))


def g_and(*xs):
    return mk(AND, xs)


def g_or(*xs):
    return mk(OR, xs)


def g_xor(a, b):
    return mk(XOR, (a, b))


def g_not(a):
    return neg(a)


def g_nor(a, b):
    return neg(g_or(a, b))


def g_nand(a, b):
    return neg(g_and(a, b))


# ---------------------------------------------------------------------------
MNEM_FMT = {}


# Emission depth limit.  Expressions in the compiled netlist nest at most ~36
# levels deep (carry chains and priority decoders are the deep ones), so this
# must stay above that or the emitted netlist silently loses recovered logic.
def node_count(n, limit=None):
    """number of operator nodes in an expression, or >= limit (early exit).

    Iterative with a visited set: expressions are shared DAGs (the compiler
    chains a whole cone into one accumulator), so a naive walk revisits nodes
    exponentially."""
    cnt = 0
    seen = set()
    stack = [n]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if is_clause(cur):
            cnt += 1
            if limit is not None and cnt >= limit:
                return cnt
            for _s, a in clause_lits(cur):
                if is_clause(a):
                    stack.append(a)
    return cnt


def graph_nodes(n, limit=None):
    """number of distinct operator nodes in the expression *graph*.

    Visited-set keyed by object identity (`id()`), not by value: expressions
    are tuples containing large frozensets, and *hashing* them is O(size of the
    set), which turns these walks quadratic on the init pass's megacones.
    Identity is the right key anyway -- every node is a distinct object."""
    cnt = 0
    seen = {}
    stack = [n]
    while stack:
        cur = stack.pop()
        cid = id(cur)
        if cid in seen:
            continue
        seen[cid] = cur
        if is_clause(cur):
            cnt += 1
            if limit is not None and cnt >= limit:
                return cnt
            for _s, a in clause_lits(cur):
                if is_clause(a):
                    stack.append(a)
    return cnt


def fmt_budget(n, names=None, max_nodes=200):
    """format an expression, refusing to expand huge cone graphs.

    A statement whose operator graph exceeds `max_nodes` is summarised instead
    of printed: printing it would expand shared sub-expressions into a tree of
    millions of characters.  The summary keeps the top operator and the node
    count, and `netlist_slice.py --dump` / `graph_nodes()` are the escapes."""
    nodes = graph_nodes(n, max_nodes + 1)
    if nodes <= max_nodes:
        return fmt(n, names)
    if is_clause(n):
        return "<cone %s%d : %d nodes>" % (n[0], len(clause_lits(n)), nodes)
    return "<cone : %d nodes>" % nodes


def fmt_let(n, names=None, max_nodes=4000):
    """format an expression as a linear *netlist* with shared nodes bound.

    Printing a cone as a tree expands shared sub-expressions exponentially: a
    graph of 50 nodes in this model prints to 3.5 MB, and the init pass has
    cones of thousands of nodes.  The compiler's accumulators make exactly that
    shape (each step re-uses the previous expression), so the faithful and
    compact rendering is a sequence of bindings:

        t1 = ~w1_6c93
        t2 = (w1_7a02 | w1_7a03)
        out = (~t1 & t2)

    Every node reachable more than once becomes a binding, so the output is
    linear in the graph size and nothing is lost.  Returns (bindings, root) or
    (None, summary) when the graph exceeds `max_nodes`."""
    # ---- collect reachable nodes and reference counts (iterative) ----
    # keyed by identity: see graph_nodes() for why value hashing is quadratic
    order = []
    obj = {}                    # id -> node (keeps the object alive)
    refs = collections.Counter()
    stack = [n]
    while stack:
        cur = stack.pop()
        cid = id(cur)
        if cid in obj:
            continue
        obj[cid] = cur
        order.append(cur)
        if is_clause(cur):
            for _s, a in clause_lits(cur):
                if is_clause(a):
                    refs[id(a)] += 1
                    stack.append(a)
    if len(order) > max_nodes:
        if is_clause(n):
            return None, "<cone %s%d : %d nodes>" % (n[0],
                                                     len(clause_lits(n)),
                                                     len(order))
        return None, "<cone : %d nodes>" % len(order)

    shared = [x for x in order if refs.get(id(x), 0) > 1]
    if not shared:
        return [], fmt(n, names)

    sid = {}
    for i, x in enumerate(sorted(shared, key=lambda y: refs[id(y)],
                                 reverse=True)):
        sid[id(x)] = "t%d" % (i + 1)

    def emit(node):
        if is_clause(node):
            return _emit_clause(node)
        s, a = node
        return ("~" + emit_atom(a)) if s else emit_atom(a)

    def emit_atom(a):
        if is_clause(a):
            if id(a) in sid:
                return sid[id(a)]
            return _emit_clause(a)
        return fmt_atom(a, names)

    def _emit_clause(node):
        op, lits = node[0], clause_lits(node)
        sym = {AND: ' & ', OR: ' | ', XOR: ' ^ '}[op]
        parts = []
        for s, a in sorted(lits, key=lambda t: repr(t[1])):
            parts.append(("~" + emit_atom(a)) if s else emit_atom(a))
        body = "(" + sym.join(parts) + ")"
        if op == XOR and clause_parity(node):
            body = "~" + body
        return body

    # ---- emit bindings (dependencies first) and the root ----
    bindings = []
    done = set()

    def dep_order(node):
        """post-order over clause children, so bindings are dependency-correct"""
        stack = [(node, False)]
        while stack:
            cur, expanded = stack.pop()
            if is_clause(cur):
                cid = id(cur)
                if expanded:
                    bindings.append(cur)
                    continue
                if cid in done:
                    continue
                done.add(cid)
                stack.append((cur, True))
                for _s, a in clause_lits(cur):
                    if is_clause(a) and id(a) not in done:
                        stack.append((a, False))

    for x in sorted(shared, key=lambda y: refs[id(y)], reverse=True):
        dep_order(x)

    out = []
    emitted = set()
    for node in bindings:
        nid = id(node)
        if nid in emitted or nid not in sid:
            continue
        emitted.add(nid)
        out.append((sid[nid], emit(node)))
    root_ref = sid.get(id(n))
    if root_ref is None:
        root_ref = emit(n)
    return out, root_ref


FMT_MAX_DEPTH = 24          # nesting depth before a cone is elided
FMT_MAX_ITEMS = 24          # literals printed per clause before eliding

# Emission budget for the whole helper call.  Printing is only *guaranteed*
# linear if it cannot exceed a fixed number of characters, because a cone with
# thousands of literals can otherwise expand without bound even with depth and
# per-clause caps.
FMT_BUDGET = 2000


def fmt(n, names=None, depth=0, max_items=None, budget=None):
    """print an expression with hard caps on depth, clause width and length.

    The caps are what make printing tractable: the compiled netlist contains
    single clauses with thousands of literals and cones that share
    sub-expressions, so an unbounded printer expands a 50-node graph into
    megabytes.  Everything elided is replaced by a visible marker (`...`),
    never silently dropped; `fmt_let()` prints a specific statement faithfully
    as a sequence of bindings instead."""
    if budget is None:
        budget = [FMT_BUDGET]
    if depth > FMT_MAX_DEPTH or budget[0] <= 0:
        return "..."
    mi = FMT_MAX_ITEMS if max_items is None else max_items
    if is_clause(n):
        op, lits = n[0], clause_lits(n)
        sym = {AND: ' & ', OR: ' | ', XOR: ' ^ '}[op]
        # A clause can hold thousands of literals, and literals can hold
        # clauses: sorting them (with a repr-key) costs more than printing them
        # and is what makes naive printing explode.  Sort only small clauses,
        # and for large ones materialise just the literals actually printed.
        nlits = len(lits)
        if nlits > mi:
            sel = []
            for x in lits:
                sel.append(x)
                if len(sel) >= mi:
                    break
            extra = nlits - mi
        else:
            sel = sorted(lits, key=lambda t: (_atom_key(t[1])))
            extra = 0
        parts = []
        for s, a in sel:
            if budget[0] <= 0:
                parts.append("...")
                break
            t = fmt_atom(a, names, depth + 1, mi, budget)
            budget[0] -= len(t) + 2
            parts.append(("~" + t) if s else t)
        body = "(" + sym.join(parts)
        if extra:
            body += " %s ...%d more..." % (sym, extra)
        body += ")"
        if op == XOR and clause_parity(n):
            body = "~" + body
        return body
    s, a = n
    t = fmt_atom(a, names, depth + 1, mi, budget)
    return ("~" + t) if s else t


def _atom_key(a):
    """cheap, total ordering key for an atom (no repr of whole sub-cones)"""
    t = a[0]
    if t == 's':
        return (0, a[1], a[2])
    if t == 'p':
        return (1, a[1], a[2])
    if t == 'c':
        return (2, a[1], 0)
    if t == 'f':
        return (3, a[1], a[2])
    if t == 'x':
        return (4, a[1], 0)
    if is_clause(a):
        return (5, len(a[1]), a[0])
    return (9, 0, 0)


def fmt_atom(a, names=None, depth=0, max_items=None, budget=None):
    t = a[0]
    if t == 's':
        nm = names.get(a[2], "") if names else ""
        short = nm.split(".")[-1] if nm else ""
        return "w%d_%04x%s" % (a[1], a[2], ("<" + short + ">") if short else "")
    if t == 'p':
        return "mem_r%d[%d]" % (a[1], a[2])
    if t == 'x':
        return "in_r%d" % a[1]
    if t == 'c':
        return str(a[1])
    if t == 'f':
        return "f%d_%d" % (a[1], a[2])
    if is_clause(a):
        return fmt(a, names, depth + 1, max_items, budget)
    return repr(a)


# ---------------------------------------------------------------------------
class Slicer(object):
    """symbolic register tracking over one executed pass"""

    def __init__(self, s, names=None, regvals=None):
        self.s = s
        self.names = names or {}
        # exact register file at store sites (from gt_regs.py): maps
        # "<addr>:<occurrence>" -> [r0..r31].  With it, values that entered a
        # fragment in a register become concrete constants instead of `in_rN`.
        self.regvals = regvals
        self.occ = {}
        self.R = {}                 # reg -> node
        self.defsite = {}           # reg -> address of its defining instruction
        self.prov = {}              # reg -> ('BANK', k, slot) provenance of the
                                    #        *value* (a state wire), when the
                                    #        register is a copy of one
        self.bmask = {}             # reg -> bytes whose value the bit model
                                    #        knows (0 = opaque word, e.g. a
                                    #        loaded vector)
        self.wsrc = {}              # reg -> address of the lwz that loaded its
                                    #        word value, while unmodified
        self.statements = []        # (addr, bank, slot, node, byte_mask)
        self.cur_addr = 0

    def reset(self):
        self.R = {}

    def _slot_read(self, base_reg, disp):
        """resolve a bank-relative read, following the value of the base"""
        s = self.s
        v = self.R.get(base_reg)
        return ('s', base_reg - 13, disp & 0xFFFF)

    def _field(self, kind, at):
        """a value produced by bit packing / address arithmetic.

        With the recorded register file the exact bit is known; otherwise the
        atom stays symbolic as `f<kind>_<addr>`."""
        rv = self._reg_value_at(self.s.regs(self.s.addr2i[at])[0], at)
        if rv is not None:
            return lit(0, ('c', rv & 1))
        return lit(0, ('f', kind, at))

    def _reg_value_at(self, reg, at, occurrence=None):
        """exact value of `reg` at instruction address `at` (and occurrence)"""
        if not self.regvals:
            return None
        if occurrence is None:
            occurrence = self.occ.get(at, 0)
        key = "%08x:%d" % (at, occurrence)
        row = self.regvals.get(key)
        if row is None:
            return None
        return row[reg] if reg < len(row) else None

    def _in(self, reg):
        """value of a register the fragment does not define: either the exact
        recorded constant (gt_regs.py) or an opaque input `in_rN`."""
        v = self.R.get(reg)
        if v is not None:
            return v
        rv = self._reg_value(reg)
        if rv is not None:
            return lit(0, ('c', rv & 1))
        return lit(0, ('x', reg))

    def _reg_value(self, reg):
        """exact value of `reg` at the current site, if recorded"""
        return self._reg_value_at(reg, self.cur_addr)

    def step(self, a):
        s = self.s
        i = s.addr2i.get(a)
        if i is None:
            return
        self.occ[a] = self.occ.get(a, 0) + 1
        self.cur_addr = a
        mn = s.mn[i]
        r = s.recs[i]
        rt, ra, rb = s.regs(i)
        f0 = r[3]
        flags = r[8]
        bank_ok = bool(flags & 2) and 13 <= ra <= 20

        if mn in ("lbz", "lhz", "lha", "lwz", "lbzu", "lwzu", "lmw"):
            if bank_ok:
                self.R[rt] = lit(0, ('s', ra - 13, s.slot[i]))
                self.prov.pop(rt, None)
            elif ra in self.prov:
                # the base register holds the *address* of a state wire (it was
                # copied out of a bank): this is a read of that wire, not of an
                # opaque pointer
                b = self.prov[ra]
                self.R[rt] = lit(0, ('s', b[0], b[1]))
                self.prov[rt] = (b[0], b[1])
            else:
                # a read through a non-bank pointer: record *where* the base
                # register was set up, so the reader can resolve the effective
                # address against a memory image
                self.R[rt] = lit(0, ('p', self.defsite.get(ra, -1), f0))
                self.prov.pop(rt, None)
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            # a freshly loaded register is an opaque value: the bit-level
            # model knows none of its bytes until they are assembled.  If the
            # register is never touched in between, a store of it is an exact
            # whole-word copy from its source slot (see wsrc).
            self.bmask[rt] = 0
            self.wsrc[rt] = a
        elif mn in ("stb", "sth", "stw", "stmw", "stbu", "sthu", "stwu"):
            v = self.R.get(rt)
            if v is None:
                v = self._in(rt)
            if bank_ok:
                # Bytes whose value the bit-level model knows.  A value
                # assembled bit by bit carries exactly the bytes it inserted;
                # a register holding an untouched loaded word (mask 0) stores
                # that word verbatim -- an exact multi-byte copy, recorded as
                # its source instead of as one boolean expression.
                bmask = self.bmask.get(rt, 0x01)
                wsrc = self.wsrc.get(rt)
                if bmask or wsrc is None:
                    self.statements.append(
                        (a, ra - 13, s.slot[i], v, bmask))
                else:
                    src = self._word_source_of(wsrc)
                    self.statements.append(
                        (a, ra - 13, s.slot[i], v, 0, src))
        elif mn == "and":
            self.R[rt] = g_and(self._in(ra),
                               self._in(rb))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x01
        elif mn == "andc":
            self.R[rt] = g_and(self._in(ra),
                               g_not(self._in(rb)))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x01
        elif mn == "or":
            self.R[rt] = g_or(self._in(ra),
                              self._in(rb))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x01
        elif mn == "orc":
            self.R[rt] = g_or(self._in(ra),
                              g_not(self._in(rb)))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x01
        elif mn == "nor":
            self.R[rt] = g_nor(self._in(ra),
                               self._in(rb))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x01
        elif mn == "nand":
            self.R[rt] = g_nand(self._in(ra),
                                self._in(rb))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x01
        elif mn == "xor":
            self.R[rt] = g_xor(self._in(ra),
                               self._in(rb))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x01
        elif mn == "eqv":
            self.R[rt] = g_not(g_xor(self._in(ra),
                                     self._in(rb)))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x01
        elif mn == "mr":
            self.R[rt] = self._in(ra)
            self.defsite[rt] = self.defsite.get(ra, a)
            if ra in self.prov:
                self.prov[rt] = self.prov[ra]
            else:
                self.prov.pop(rt, None)
        elif mn in ("li",):
            sd = f0 - 0x100000000 if f0 & 0x80000000 else f0
            self.R[rt] = lit(0, ('c', sd & 1))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
        elif mn in ("lis", "addis"):
            self.R[rt] = lit(0, ('c', 0))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
        elif mn in ("addi",):
            sd = f0 - 0x100000000 if f0 & 0x80000000 else f0
            v = self.R.get(ra)
            if sd == 0 and v is not None:
                self.R[rt] = v
                self.defsite[rt] = self.defsite.get(ra, a)
                if ra in self.prov:
                    self.prov[rt] = self.prov[ra]
                else:
                    self.prov.pop(rt, None)
            else:
                self.R[rt] = lit(0, ('f', 0, a))
                self.defsite[rt] = a
            self.wsrc.pop(rt, None)
        elif mn in ("ori", "oris", "xori", "xoris"):
            self.R[rt] = self._field(1, a)
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x0F if mn in ("oris", "xoris") else 0x01
        elif mn in ("slwi", "rlwimi", "rlwinm", "srwi", "clrlwi", "extlwi",
                    "extrwi", "rlwnm"):
            self.R[rt] = self._field(2, a)
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            # which bytes of the destination does this instruction assemble?
            # PPC bit 0 is the MSB, so bit b lives in byte b // 8.
            self.bmask[rt] = self._rot_bytes(i)
        elif mn in ("mulli", "add", "subfc"):
            self.R[rt] = self._field(3, a)
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)
            self.bmask[rt] = 0x0F
        elif mn in ("cmplwi", "cmpwi", "cmplw", "cmpw", "beq", "bne", "b",
                    "bc", "bdnz", "mtlr", "mflr", "blr", "blrl", "bl"):
            pass
        else:
            self.R[rt] = lit(0, ('f', 9, a))
            self.defsite[rt] = a
            self.wsrc.pop(rt, None)

    def _word_source_of(self, load_addr):
        """(source address, bank, slot) of the word a register was loaded with.

        The load address is the instruction address; the record gives the
        effective address, so `lwz` from a known base yields a real state
        address and the store is an exact 4-byte copy from there."""
        s = self.s
        i = s.addr2i.get(load_addr)
        if i is None or not (s.recs[i][8] & 2):
            return None
        return (load_addr, s.bank[i], s.slot[i])

    def _rot_bytes(self, i):
        """byte mask assembled by a rotate/mask instruction.

        PPC numbers bits from the MSB (bit 0 = 0x80000000), so bit b lives in
        byte b // 8.  For `rlwimi rA, rS, sh, mb, me` the inserted field is
        bits mb..me of the *result*, which is what the netlist drives."""
        s = self.s
        mn = s.mn[i]
        f0, f1, f2 = s.recs[i][3], s.recs[i][4], s.recs[i][5]
        if mn in ("rlwimi", "rlwinm"):
            lo, hi = min(f1, f2), max(f1, f2)
        elif mn in ("clrlwi",):
            lo, hi = f0, 31
        elif mn in ("slwi",):
            lo, hi = 32 - f0 if f0 else 0, 31
        elif mn in ("srwi",):
            lo, hi = 0, 31 - f0
        elif mn in ("extlwi",):
            lo, hi = f0, f0 + f1 - 1
        elif mn in ("extrwi",):
            lo, hi = 32 - f0 - f1, 31
        else:
            return 0x0F
        if lo < 0:
            lo = 0
        if hi > 31:
            hi = 31
        if hi < lo:
            return 0x0F
        mask = 0
        for b in range(lo, hi + 1):
            mask |= 1 << (3 - (b // 8))
        return mask or 0x01

    # ------------------------------------------------------------------
    def run_pass(self, addrs):
        for a in addrs:
            self.step(a)
        return self.statements


# ---------------------------------------------------------------------------
_CLS_CACHE = {}


def classify(node, depth=0, maxd=64):
    """structural family key of an expression (the 'gene' signature).

    Literals collapse to their kind (s = any state wire, p = memory/array,
    x = external, cN = constant); clauses keep operator and arity, so the key
    describes the *shape* of the logic element independent of its ports.
    Memoised: expression nodes are immutable tuples and are shared between
    statements, so identical sub-expressions are classified once."""
    if depth == 0:
        hit = _CLS_CACHE.get(node)
        if hit is not None:
            return hit
    if depth > maxd:
        return "*"
    if is_clause(node):
        op, lits = node[0], clause_lits(node)
        items = sorted(classify_lit(x, depth + 1, maxd) for x in lits)
        par = clause_parity(node) if op == XOR else 0
        res = "%s%d%s(%s)" % (op, len(lits), "~" if par else "",
                              ",".join(items))
    else:
        res = classify_lit(node, depth, maxd)
    if depth == 0:
        _CLS_CACHE[node] = res
    return res


def classify_lit(n, depth, maxd):
    if is_clause(n):
        return classify(n, depth, maxd)
    if not (isinstance(n, tuple) and len(n) == 2 and isinstance(n[0], int)):
        raise TypeError("not a literal: %r" % (n,))
    s, a = n
    t = a[0] if isinstance(a, tuple) and isinstance(a[0], str) else '?'
    if t == 's':
        return ("~" if s else "") + "s"
    if t in ('p', 'x'):
        return ("~" if s else "") + t
    if t == 'c':
        return ("~" if s else "") + "c%d" % a[1]
    if t == 'f':
        return ("~" if s else "") + "f%d" % a[1]
    if is_clause(a):
        return ("~" if s else "") + str(classify(a, depth, maxd))
    return ("~" if s else "") + "?"


def stmt_parts(st):
    """(addr, bank, slot, node, byte_mask, word_source) for a statement.

    * `byte_mask` says which bytes of the destination this statement drives.
      A value assembled bit by bit carries exactly the bytes it inserted, so a
      single-bit wire is checked in the byte it actually lives in.
    * `word_source` is set for a statement that copies a whole word (`lwz`
      followed by `stw`, mask 0): it names the source state address, so the
      copy is verified byte-exactly instead of being reduced to one bit."""
    addr, bank, slot, node, bmask = stmt_parts5(st)
    wsrc = st[5] if len(st) >= 6 else None
    return addr, bank, slot, node, bmask, wsrc


def stmt_parts5(st):
    if len(st) >= 5:
        return st[0], st[1], st[2], st[3], st[4]
    return st[0], st[1], st[2], st[3], 0x01


def load_trace(path="research/gt_exec.json"):
    """ground truth from the interpreter: executed addresses + exact
    execution order per pass (sorting addresses is NOT execution order --
    the netlist contains backward branches)."""
    d = json.load(open(path))
    ex = {int(k, 16): v for k, v in d["exec_cnt"].items()}
    return d, ex


def order_for(d, region):
    """execution order (list of addresses, repeats included) for a region"""
    if region == "init":
        return d.get("init_order") or sorted(
            a for a in (int(k, 16) for k in d["exec_cnt"]) if a < 0x1BCD60)
    cyc = d.get("order", {}).get("cycle0", {})
    if region == "cycle1":
        return cyc.get("stage1") or []
    if region == "cycle2":
        return cyc.get("stage3") or []
    return []


def family_of(n, max_size=24):
    """bounded family key: full structural signature for small cones, and a
    `big(op,arity)` summary for cones too large to expand (the init pass
    contains cones of thousands of nodes; expanding them is neither useful nor
    cheap)."""
    if node_count(n, max_size + 1) > max_size:
        if is_clause(n):
            return "big(%s%d)" % (n[0], len(clause_lits(n)))
        return "big(lit)"
    return classify(n)


EMIT_HEADER = """\
# Recovered 2-value netlist of %(model)s
#
# This file IS the extracted logic-element list of the GKO model for one full
# per-cycle netlist evaluation (entry 0x2341CC), recovered by symbolic
# dataflow replay of the executed code.  See research/GKO_MACROBLOCKS_Report.md.
#
#   region: %(region)s (%(nins)d executed instructions, %(nst)d statements)
#   format: @<code address>  b<bank>.<slot>  <signal name>  <=  <expression>
#
# Notation
#   bN.MMMM     a state wire: slot MMMM (hex, 16-bit: disp & 0xFFFF) in bank N
#               (the 8 banks r13..r20 are the two-value/L1-L2 planes)
#   wN_MMMM     the same wire read as an input
#   <L1>/<L2>   the model symbol table's latch-phase suffix on a name
#   fK_ADDR     a value produced by bit packing / address arithmetic at
#               instruction ADDR (multi-bit vector assembly); K is the kind
#   mem_rN[d]   a byte read through a non-bank pointer (array/memory image)
#   in_rN       a value that entered the fragment in register rN
#   &  |  ^     recovered boolean operators (n-ary; negation is pushed to the
#               leaves by De Morgan, so `~x` is the literal x inverted)
#   c0 / c1     a constant driver (tie-off / reset default)
#
# The patch-list anchors (words patched to 0x60000000 NOPs at load time) are
# invisible here by construction: they are skipped when the logic is matched
# and never contribute to a pattern, although the code's branch offsets count
# them.  Only executed instructions are used, so there is no dead code here.
#
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="all",
                    choices=["all", "init", "cycle1", "cycle2"])
    ap.add_argument("--dump", nargs=2, metavar=("LO", "HI"))
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--families", action="store_true")
    ap.add_argument("--catalog", action="store_true",
                    help="count every distinct sub-expression pattern")
    ap.add_argument("--out", default=None, help="write the catalog to a file")
    ap.add_argument("--emit", default=None,
                    help="write the full recovered netlist to a file")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--max-size", type=int, default=24,
                    help="catalog: skip cones larger than this many nodes")
    ap.add_argument("--depth-cap", type=int, default=64,
                    help="emit: nesting depth before a cone is elided")
    ap.add_argument("--items-cap", type=int, default=100000,
                    help="emit: literals printed per clause before eliding")
    ap.add_argument("--budget", type=int, default=10 ** 9,
                    help="emit: character budget per expression")
    args = ap.parse_args()

    s = Stream()
    d, ex = load_trace()
    if args.region == "all":
        addrs = (order_for(d, "init") + order_for(d, "cycle1") +
                 order_for(d, "cycle2"))
    else:
        addrs = order_for(d, args.region)
    print("executed instructions in region '%s': %d (exact execution order)"
          % (args.region, len(addrs)))

    names = {}
    try:
        spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
        cosim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cosim)
        names = cosim.Model("model/COSIM.m2630opt.Jul1599",
                            "model/pin.list").slot_names
    except Exception as e:
        print("(names unavailable: %s)" % e)

    sl = Slicer(s, names)
    sl.run_pass(addrs)
    print("statements (state wires written): %d" % len(sl.statements))

    if args.dump:
        lo, hi = int(args.dump[0], 0), int(args.dump[1], 0)
        n = 0
        for a, bank, slot, v, bmask, _wsrc in (stmt_parts(x)
                                              for x in sl.statements):
            if lo <= a <= hi:
                print("  @%08x  b%d.%04x <= %s" % (a, bank, slot, fmt(v)))
                n += 1
        print("(%d statements in range)" % n)

    if args.emit:
        # the recovered netlist, one statement per state wire written, in
        # execution order, with the driving code address and the wire name.
        # The caps are relaxed here by default so this file stays the faithful
        # rendering; tune them with --depth-cap/--items-cap/--budget.
        with open(args.emit, "w", encoding="utf-8") as f:
            f.write(EMIT_HEADER % {"model": MODEL_PATH, "region": args.region,
                                   "nins": len(addrs),
                                   "nst": len(sl.statements)})
            for a, bank, slot, v, bmask, wsrc in (stmt_parts(x)
                                                  for x in sl.statements):
                nm = names.get(slot, "")
                if bmask == 0:
                    body = "<whole-word copy>"
                else:
                    body = fmt(v, names, max_items=args.items_cap,
                               budget=[args.budget])
                f.write("@%08x  b%d.%04x  %-46s <= %s\n"
                        % (a, bank, slot, nm, body))
        print("netlist written to", args.emit)

    if args.families:
        # Bounded aggregation: cones larger than --max-size are summarised as
        # `big(<signature of the top operator>)` instead of being expanded,
        # which keeps the pass linear even for the init pass where one
        # statement can be a 2,000-node cone.
        fam = collections.Counter()
        ex_of = {}
        for a, bank, slot, v, bmask, _wsrc in (stmt_parts(x)
                                              for x in sl.statements):
            k = family_of(v, args.max_size)
            fam[k] += 1
            ex_of.setdefault(k, (a, bank, slot, v))
        print("\n== macroblock families (structural signature of the driver) ==")
        for k, c in fam.most_common(args.top):
            a, bank, slot, v = ex_of[k]
            print("%7d  %-62s e.g. @%08x b%d.%04x" %
                  (c, k[:62], a, bank, slot))
        print("\ndistinct families: %d" % len(fam))

    if args.catalog:
        # Every distinct sub-expression, counted over all statements: the
        # primitive ("smallest, most frequent") ones are the macroblocks the
        # compiler emits, i.e. the logic elements of the original schematic.
        sub = collections.Counter()
        ex_of = {}
        size = {}
        # statements can contain very large cones (up to ~2,000 nodes); a
        # bounded, visited-set walk keeps the catalog linear and focused on
        # the *primitive* (small) shapes that the question is about
        max_size = args.max_size

        def walk(n, seen, depth=0):
            if depth > 24:
                return
            key = classify(n)
            if key not in seen:
                seen.add(key)
                sub[key] += 1
                if key not in ex_of:
                    ex_of[key] = n
                    size[key] = expr_size(n)
            if is_clause(n):
                for s, a in clause_lits(n):
                    if is_clause(a):
                        walk(a, seen, depth + 1)

        def expr_size(n):
            if is_clause(n):
                return 1 + sum(expr_size(a) for s, a in clause_lits(n)
                               if is_clause(a))
            return 1

        for a, bank, slot, v, bmask, _wsrc in (stmt_parts(x)
                                              for x in sl.statements):
            if expr_size(v) <= max_size:
                walk(v, set())

        print("\n== macroblock catalog: %d distinct sub-expressions =="
              % len(sub))
        print("%9s %6s  %s" % ("count", "size", "pattern"))
        rows = []
        for k, c in sub.items():
            rows.append((size.get(k, 0), c, k))
        for s, c, k in sorted(rows, key=lambda r: (r[0], -r[1]))[:args.top]:
            print("%9d %6d  %s" % (c, s, k[:90]))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write("# count\tsize\tpattern\n")
                for s, c, k in sorted(rows, key=lambda r: (r[0], -r[1])):
                    f.write("%d\t%d\t%s\n" % (c, s, k))
            print("catalog written to", args.out)


if __name__ == "__main__":
    main()
