#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netlist_trace.py -- register/value tracing over the compiled netlist stream.

The compiled model addresses its state through *computed pointers*: the eight
state banks are contiguous (r13 = model base + 0x8000, +0x10000 each), and the
generated code frequently walks a latch plane with an incremented register
(`lbz r0, disp(r185)`).  To recover the netlist we must resolve every memory
access to a (bank, slot) pair, i.e. to a named state wire.

This module propagates a small abstract value per register:

    ('BANK', k, off)   address = base_of_bank(k) + off   (k = 0..7, or -1 for
                       the "context block" at model base + 0)
    ('CONST', v)       known integer constant
    ('UNK',)           unknown (block input / array pointer / sum of unknowns)

Tracking is done over the *executed* instruction order with branches followed
(fall-through plus `beq`/`bne`/`b` targets) for the linear netlist regions.

Usage:
    python3 netlist_trace.py --addr 0x247384 --count 40 --before 60
"""
import argparse
import sys

from netlist_stream import Stream, F_PATCH, F_BANK

BANK_BASE = 0x8000          # bank 0 base inside the context block
BANK_STRIDE = 0x10000


class Tracer(object):
    def __init__(self, s, names=None):
        self.s = s
        self.names = names or {}
        self.reg = {}
        self.reset()

    def reset(self):
        self.reg = {i: ('UNK',) for i in range(32)}
        # bootstrap: r13 = cb + 0x8000, r14..r20 = +0x10000 each
        for k in range(8):
            self.reg[13 + k] = ('BANK', k, 0)

    # ------------------------------------------------------------------
    @staticmethod
    def _imm32(v):
        return v - 0x100000000 if v & 0x80000000 else v

    def bank_of(self, i):
        """if the base register of a memory op is a known bank, return
        (bank, offset) else None"""
        a, t, raw, f0, f1, f2, rg, slot, flags, _ = self.s.recs[i]
        rA = rg & 0xFF
        v = self.reg.get(rA, ('UNK',))
        if v[0] == 'BANK':
            sd = self._imm32(f0)
            return (v[1], v[2] + sd)
        return None

    def step(self, i):
        s = self.s
        a, t, raw, f0, f1, f2, rg, slot, flags, _ = s.recs[i]
        mn = s.mon[t]
        rA, rB, rC, rD = s.regs(i)
        R = self.reg
        if flags & F_PATCH:
            return
        if mn in ("addi",):
            v = R.get(rA, ('UNK',))
            imm = self._imm32(f0)
            R[rC] = self._add(v, ('CONST', imm))
        elif mn in ("addis",):
            v = R.get(rA, ('UNK',))
            imm = self._imm32(f0) << 16
            R[rC] = self._add(v, ('CONST', imm))
        elif mn in ("li",):
            R[rC] = ('CONST', self._imm32(f0))
        elif mn in ("lis",):
            R[rC] = ('CONST', (self._imm32(f0) << 16) & 0xFFFFFFFF)
        elif mn in ("ori", "oris", "xori", "xoris"):
            v = R.get(rA, ('UNK',))
            iv = f0 if mn in ("ori", "xori") else (f0 << 16)
            if v[0] == 'CONST':
                nv = (v[1] | iv) if mn in ("ori", "oris") else (v[1] ^ iv)
                R[rC] = ('CONST', nv & 0xFFFFFFFF)
            else:
                R[rC] = ('UNK',)
        elif mn in ("lbz", "lhz", "lha", "lwz", "lwzu", "lbzu", "lmw"):
            R[rC] = ('UNK',)
        elif mn in ("mr",):
            R[rC] = R.get(rA, ('UNK',))
        elif mn in ("add",):
            R[rC] = self._add(R.get(rA, ('UNK',)), R.get(rB, ('UNK',)))
        elif mn in ("slwi",):
            v = R.get(rA, ('UNK',))
            R[rC] = ('SCALE', v, f0) if v[0] == 'CONST' else ('UNK',)
        elif mn in ("rlwinm", "rlwimi", "srwi", "clrlwi", "extlwi", "extrwi"):
            R[rC] = ('UNK',)
        elif mn in ("mulli",):
            v = R.get(rA, ('UNK',))
            if v[0] == 'CONST':
                R[rC] = ('CONST', (v[1] * self._imm32(f0)) & 0xFFFFFFFF)
            else:
                R[rC] = ('UNK',)
        elif mn == "mtlr":
            R[32] = R.get(rA, ('UNK',))
        else:
            pass

    @staticmethod
    def _add(a, b):
        if a[0] == 'CONST' and b[0] == 'CONST':
            return ('CONST', (a[1] + b[1]) & 0xFFFFFFFF)
        if a[0] == 'BANK' and b[0] == 'CONST':
            return ('BANK', a[1], a[2] + b[1])
        if b[0] == 'BANK' and a[0] == 'CONST':
            return ('BANK', b[1], b[2] + a[1])
        return ('UNK',)

    # ------------------------------------------------------------------
    def run(self, start, n_ins):
        s = self.s
        i = s.addr2i.get(start)
        if i is None:
            raise SystemExit("no code at 0x%x" % start)
        out = []
        for _ in range(n_ins):
            r = s.recs[i]
            out.append((i, self.bank_of(i)))
            self.step(i)
            i += 1
            if i >= s.n:
                break
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", type=lambda x: int(x, 0), default=0x247384)
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--before", type=int, default=0)
    args = ap.parse_args()

    s = Stream()
    tr = Tracer(s)
    start = args.addr - 4 * args.before
    res = tr.run(start, args.before + args.count)
    for i, resolved in res:
        r = s.recs[i]
        tag = ""
        if resolved:
            tag = " => bank %d slot %04x" % (resolved[0], resolved[1] & 0xFFFF)
        print("%08x  %-40s%s" % (r[0], s.shape(i), tag))


if __name__ == "__main__":
    main()
