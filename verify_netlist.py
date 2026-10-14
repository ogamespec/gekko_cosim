#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_netlist.py -- check the reconstructed netlist against the compiled
model.

The reconstructed statements (see netlist_slice.py) are replayed as a pure
netlist over the 8 state banks and the result is compared with the state the
compiled model actually produced (ground truth captured by gt_dump.py).

For each observation point:

  1. read the "before" banks (8 x 64 KiB from research/gt_state/*.bin);
  2. starting from the bank image of the *pre* state -- for the init pass
     that is all zeros, exactly the interpreter's initial state -- evaluate
     every extracted statement in execution order, following the executed
     trace, and write each result into the same bank image;
  3. compare bank image with the "after" banks.

The comparison is reported per statement and aggregated over the slots the
netlist drives, so it is a per-gate correctness check of the extraction.

Usage:
    python3 verify_netlist.py --pass init
    python3 verify_netlist.py --pass cycle --cycle 0
    python3 verify_netlist.py --all
"""
import argparse
import importlib.util
import sys
import json
import os
import struct

import netlist_slice as ns
from netlist_stream import Stream

BANK_BASE = 0x8000
BANK_SIZE = 0x10000
STATE_DIR = "research/gt_state"
STATE_SIZE = 0x500000            # cosim.py's state memory size


def cosim_state_size():
    return STATE_SIZE


def load_banks(path):
    raw = open(path, "rb").read()
    return [raw[b * BANK_SIZE:(b + 1) * BANK_SIZE] for b in range(8)]


def banks_to_bytes(banks):
    return bytearray(b"".join(bytes(b) for b in banks))


def apply_statements(sl, pre_banks, after_banks, only_closed=False,
                     ctx_mem=None):
    """evaluate the statements against the pre-state.

    `only_closed` restricts the check to *closed* statements: those whose
    value depends only on state wires, constants and field arithmetic.  A
    statement that reads the memory image through a non-bank pointer
    (`mem_rN[d]`) or inherits a value in a register (`in_rN`) cannot be
    evaluated from the bank image alone -- the interpreter holds that data in
    its 5 MB state memory -- so those are counted separately.
    """
    mem = banks_to_bytes(pre_banks)
    ctx = {'mem': ctx_mem, '_memo': {}}
    n_checked = n_ok = n_open = 0
    mismatches = []
    for st in sl.statements:
        a, bank, slot, v, bmask, wsrc = ns.stmt_parts(st)
        closed = is_closed(v)
        if only_closed and not closed:
            continue
        # state changes between statements, so the memo is per statement: it
        # shares sub-expressions *within* one (possibly huge) cone
        ctx['_memo'] = {}
        val = eval_node(v, mem, ctx) & 1
        real = after_banks[bank][slot & 0xFFFF]
        off = _slot_off(bank, slot)
        if bmask:
            mem[off] = val
        n_checked += 1
        if not closed:
            n_open += 1
        if val == real:
            n_ok += 1
        else:
            mismatches.append((a, bank, slot, val, real, v, closed))
    return n_checked, n_ok, mismatches, n_open


def is_closed(n):
    """True if the expression depends only on state wires and constants.

    A `('p', addr, disp)` atom reads the memory image at a known address, so
    with a full memory snapshot it *is* evaluable; only values inherited from
    outside the fragment (`in_rN`) stay unknown."""
    if ns.is_clause(n):
        return all(is_closed_lit(x) for x in ns.clause_lits(n))
    return is_closed_lit(n)


def is_closed_lit(x):
    s, a = x
    if ns.is_clause(a):
        return is_closed(a)
    return a[0] in ('s', 'c', 'p')


def _slot_off(bank, slot):
    """byte offset of (bank, slot) inside the concatenated bank image"""
    d = slot - 0x10000 if slot >= 0x8000 else slot
    return bank * BANK_SIZE + d


def slot_addr(bank, slot):
    d = slot - 0x10000 if slot >= 0x10000 else slot
    if slot >= 0x8000:
        d = slot - 0x10000
    return BANK_BASE + bank * BANK_SIZE + d


class BankState(object):
    """the 8 banks seen as byteaddressable state (banks are contiguous)"""

    def __init__(self, m=None, banks=None):
        self.m = m if m is not None else bytearray(8 * BANK_SIZE)
        self.banks = banks

    def rd(self, addr):
        return self.m[addr - BANK_BASE]

    def wr(self, addr, v):
        self.m[addr - BANK_BASE] = v & 0xFF


def eval_node(n, mem, ctx):
    """evaluate a reconstructed expression against a bank image (bytearray)

    Recursive over the expression tree with short-circuiting; clause members
    that are plain state wires are read directly out of the bank image.  The
    caller raises the recursion limit because some cones are deep.

    A per-call memo (`ctx['_memo']`) makes shared sub-expressions evaluate
    once: the init pass chains a whole cone into one accumulator register, so
    without it every statement would re-walk the entire cone."""
    memo = ctx.get('_memo')
    if memo is not None:
        hit = memo.get(n)
        if hit is not None:
            return hit
    if not ns.is_clause(n):
        s, a = n
        v = _rd_atom(a, mem, ctx)
        res = (v if s == 0 else (1 - v)) & 1
    else:
        op = n[0]
        lits = ns.clause_lits(n)
        res = 0
        if op == ns.AND:
            res = 1
            for x in lits:
                if _eval_lit(x, mem, ctx) == 0:
                    res = 0
                    break
        elif op == ns.OR:
            for x in lits:
                if _eval_lit(x, mem, ctx) == 1:
                    res = 1
                    break
        elif op == ns.XOR:
            r = ns.clause_parity(n)
            for x in lits:
                r ^= _eval_lit(x, mem, ctx) & 1
            res = r & 1
    if memo is not None:
        memo[n] = res
    return res


def _eval_lit(x, mem, ctx):
    s, a = x
    if a[0] == 's':
        sl = a[2]
        v = mem[sl - 0x10000 if sl >= 0x8000 else sl]
        return (v if s == 0 else (1 - v)) & 1
    v = _rd_atom(a, mem, ctx)
    return (v if s == 0 else (1 - v)) & 1


def _rd_atom(a, mem, ctx):
    t = a[0]
    if t == 's':
        sl = a[2]
        return mem[sl - 0x10000 if sl >= 0x8000 else sl]
    if t == 'c':
        return a[1] & 1
    if t == 'p':
        # a byte read through a non-bank pointer: a[1] is the address of the
        # instruction that set the base register up, so its effective address
        # is known and the full pre-state memory image (ctx['mem']) supplies
        # the value -- the interpreter holds that data, not the bank image
        m = ctx.get('mem')
        if m is not None and a[1] >= 0:
            return m[a[1]] if a[1] < len(m) else 0
        return ctx.get(('p', a[1], a[2]), 0)
    if t == 'x':
        return ctx.get(('x', a[1]), 0)
    if t == 'f':
        return ctx.get(('f', a[1], a[2]), 0)
    if ns.is_clause(a):
        return eval_node(a, mem, ctx)
    return 0



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="pas", default="cycle",
                    choices=["init", "cycle", "cycle1", "cycle2", "all"])
    ap.add_argument("--cycle", type=int, default=0)
    ap.add_argument("--trace", default="research/gt_exec.json")
    ap.add_argument("--regs", default="research/gt_regs.json")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--all-stmts", action="store_true",
                    help="also check statements that read the memory image")
    args = ap.parse_args()

    sys.setrecursionlimit(100000)

    s = Stream()
    d, ex = ns.load_trace(args.trace)
    regvals = None
    if os.path.exists(args.regs):
        regvals = json.load(open(args.regs))
        print("register values at store sites: %s" % args.regs)

    regions = []
    if args.pas in ("init", "all"):
        regions.append(("init", "after_init", None))
    if args.pas in ("cycle1", "all"):
        c = args.cycle
        pre = "after_init" if c == 0 else "cycle%d" % (c - 1)
        regions.append(("cycle1", "cycle%d_mid" % c, pre))
    if args.pas in ("cycle", "cycle2", "all"):
        c = args.cycle
        pre = "cycle%d_mid" % c
        regions.append(("cycle2", "cycle%d" % c, pre))

    for kind, tag, pre_tag in regions:
        after_path = os.path.join(STATE_DIR, tag + ".bin")
        if not os.path.exists(after_path):
            print("!! missing %s -- run gt_dump.py first" % after_path)
            continue
        after = load_banks(after_path)
        if pre_tag is None:
            # the init pass starts from the interpreter's zeroed state
            before = [bytearray(BANK_SIZE) for _ in range(8)]
            ctx_mem = bytearray(cosim_state_size())
        else:
            pre_path = os.path.join(STATE_DIR, pre_tag + ".bin")
            before = load_banks(pre_path)
            mem_path = os.path.join(STATE_DIR, pre_tag + ".mem")
            ctx_mem = bytearray(open(mem_path, "rb").read()) \
                if os.path.exists(mem_path) else None

        # the netlist for this pass: the executed addresses of the pass, in
        # the interpreter's exact execution order (backward branches repeat
        # addresses, and sorting them would give the wrong dataflow)
        addrs = ns.order_for(d, kind)
        sl = ns.Slicer(s, {}, regvals=(regvals or {}).get(
            {"init": "init", "cycle1": "cycle0_stage1",
             "cycle2": "cycle0_stage3"}[kind]))
        sl.run_pass(addrs)

        n_checked, n_ok, mismatches, n_open = apply_statements(
            sl, before, after, only_closed=not args.all_stmts,
            ctx_mem=ctx_mem)
        print("\n== pass %s (%s, pre=%s) ==" % (kind, tag, pre_tag))
        print("executed instructions: %d" % len(addrs))
        if args.all_stmts:
            print("statements checked: %d (all)" % n_checked)
        else:
            print("statements total: %d, closed (bank-only) checked: %d "
                  "(open: %d)" % (len(sl.statements), n_checked, n_open))
        print("matching statements: %d / %d  (%.2f%%)"
              % (n_ok, n_checked, 100.0 * n_ok / max(1, n_checked)))
        for m in mismatches[:10]:
            a, bank, slot, val, real, v, closed = m
            print("  MISMATCH @%08x b%d.%04x: got %d expected %d   %s"
                  % (a, bank, slot, val, real,
                     ns.fmt(v)[:80]))
        if mismatches:
            print("  total mismatches: %d" % len(mismatches))


if __name__ == "__main__":
    main()
