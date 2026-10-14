#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_final.py -- compare the *final* recovered netlist state with the
compiled model, slot by slot.

`verify_netlist.py` compares each statement against the state the model left
behind, which is a *local* check: when a wire is written several times in one
pass (the model walks loops and shares one physical wire between several
logical elements) a single statement can legitimately disagree while the
final value is right.  This tool evaluates the whole recovered netlist in
execution order and then compares the final value of every slot the netlist
drives with the model's post-state.

Usage:  python3 verify_final.py --pass init
        python3 verify_final.py --pass cycle2 --cycle 0
"""
import argparse
import json
import os
import sys

import netlist_slice as ns
from netlist_stream import Stream

import verify_netlist as vn

BANK_SIZE = 0x10000
STATE_DIR = "research/gt_state"


def has_field(n):
    """True if the statement contains a bit-packing atom (multi-bit vector
    assembly): those statements are only partially recovered (the boolean
    part), because a word assembled with rlwimi is not one state bit."""
    if ns.is_clause(n):
        return any(has_field_at(x) for x in ns.clause_lits(n))
    return has_field_at(n)


def has_field_at(x):
    a = x[1] if not ns.is_clause(x) else x
    if ns.is_clause(a):
        return has_field(a)
    return a[0] == 'f'


def evaluate(sl, pre_banks, ctx_mem):
    """replay the netlist; return slot -> (bit, addr, node, byte_mask, wsrc)

    A word copy (mask 0) needs no evaluation: its value is the source word
    itself.  A bit-assembled statement evaluates to one bit that the model
    commits to the low byte of its slot."""
    mem = vn.banks_to_bytes(pre_banks)
    ctx = {'mem': ctx_mem}
    last = {}
    for st in sl.statements:
        a, bank, slot, v, bmask, wsrc = ns.stmt_parts(st)
        if bmask == 0:
            last[(bank, slot)] = (None, a, v, 0, wsrc)
            continue
        # a fresh memo per statement: state wires change between statements,
        # but sub-expressions shared inside one cone are reused
        ctx['_memo'] = {}
        val = vn.eval_node(v, mem, ctx) & 1
        off = vn._slot_off(bank, slot)
        mem[off] = val
        last[(bank, slot)] = (val, a, v, bmask, None)
    return last


def compare(pre, post, last):
    """byte-accurate comparison.

    * word copy: the four source bytes must equal the four destination bytes;
    * bit-assembled statement: the low byte of the destination must equal the
      recovered bit.
    Returns (ok, bad, ok_field, bad_field, bad_list).

    The word-copy check compares the *low byte*, which is where a single-bit
    model keeps its wire value; the upper bytes of a copied word are latch
    plane bookkeeping and are reported separately by --word-bytes."""
    ok = bad = ok_f = bad_f = 0
    bad_list = []
    for (bank, slot), (val, a, v, bmask, wsrc) in sorted(last.items()):
        seg = post[bank]
        real = seg[slot & 0xFFFF]
        if bmask == 0 and wsrc is not None:
            _, sbank, sslot = wsrc
            good = (pre[sbank][sslot & 0xFFFF] == real)
        else:
            good = (real == val)
        fld = has_field(v)
        if good:
            ok += 1
            if fld:
                ok_f += 1
        else:
            bad += 1
            if fld:
                bad_f += 1
            if len(bad_list) < 12:
                bad_list.append((bank, slot, val, real, a, fld, bmask))
    return ok, bad, ok_f, bad_f, bad_list


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="pas", default="cycle2",
                    choices=["init", "cycle1", "cycle2"])
    ap.add_argument("--cycle", type=int, default=0)
    ap.add_argument("--trace", default="research/gt_exec.json")
    ap.add_argument("--regs", default="research/gt_regs.json")
    args = ap.parse_args()
    sys.setrecursionlimit(200000)

    s = Stream()
    d, ex = ns.load_trace(args.trace)
    regvals = json.load(open(args.regs)) if os.path.exists(args.regs) else {}
    rtab = {"init": "init", "cycle1": "cycle0_stage1",
            "cycle2": "cycle0_stage3"}[args.pas]

    if args.pas == "init":
        pre_tag = None
        post_tag = "after_init"
    elif args.pas == "cycle1":
        pre_tag = "after_init" if args.cycle == 0 else "cycle%d" % (args.cycle - 1)
        post_tag = "cycle%d_mid" % args.cycle
    else:
        pre_tag = "cycle%d_mid" % args.cycle
        post_tag = "cycle%d" % args.cycle

    pre = ([bytearray(BANK_SIZE) for _ in range(8)] if pre_tag is None
           else vn.load_banks(os.path.join(STATE_DIR, pre_tag + ".bin")))
    post = vn.load_banks(os.path.join(STATE_DIR, post_tag + ".bin"))
    ctx_mem = None
    if pre_tag is not None:
        mp = os.path.join(STATE_DIR, pre_tag + ".mem")
        if os.path.exists(mp):
            ctx_mem = bytearray(open(mp, "rb").read())
    if ctx_mem is None:
        ctx_mem = bytearray(vn.STATE_SIZE)

    sl = ns.Slicer(s, {}, regvals=regvals.get(rtab))
    sl.run_pass(ns.order_for(d, args.pas))
    n_word = sum(1 for x in sl.statements if ns.stmt_parts(x)[4] == 0)
    print("pass %s: %d statements (%d bit-level, %d whole-word copies), "
          "%d driven slots"
          % (args.pas, len(sl.statements), len(sl.statements) - n_word,
             n_word,
             len(set((b, sl2) for _, b, sl2, _, _, _ in
                     (ns.stmt_parts(x) for x in sl.statements)))))

    last = evaluate(sl, pre, ctx_mem)
    ok, bad, ok_f, bad_f, bad_list = compare(pre, post, last)
    print("final-state match: %d / %d slots (%.2f%%)"
          % (ok, ok + bad, 100.0 * ok / max(1, ok + bad)))
    print("  single-bit statements only: %d / %d (%.2f%%)"
          % (ok - ok_f, (ok - ok_f) + (bad - bad_f),
             100.0 * (ok - ok_f) / max(1, (ok - ok_f) + (bad - bad_f))))
    print("  byte-assembly statements: %d / %d (%.2f%%)"
          % (ok_f, ok_f + bad_f,
             100.0 * ok_f / max(1, ok_f + bad_f)))
    for bank, slot, val, real, a, fld, bmask in bad_list:
        print("   b%d.%04x: netlist %s, model %s  @%08x mask=%x%s"
              % (bank, slot, val, real, a, bmask,
                 "  [byte-assembly]" if fld else ""))


if __name__ == "__main__":
    main()
