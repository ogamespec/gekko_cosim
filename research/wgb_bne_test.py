#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wgb_bne_test.py — BNE / auto-flush test for the Gekko write-gather pipe
========================================================================
Puts the model's write-gather-pipe state into a "data present" configuration
(WPE=1, WPAR address, byte counter, write-pipe pointers, LAS gather flags)
and then runs *idle* cycles (no new stores, no bus traffic) to check whether
anything decays on its own:

  * the WGB byte counter (GE0.WPC* slots) — a timer would drain it;
  * the WPAR[BNE]-candidate bit (GE0.WPAR.NAN7) — would clear on auto-flush;
  * the TS_ pin — an auto-flush would assert a bus burst request.

If the state stays frozen for hundreds of idle cycles, there is no
time-based flush in the model (consistent with the IBM Gekko User Manual
section 9.4, which documents no timeout).

Usage:  python3 wgb_bne_test.py [cycles]
"""
import sys
import importlib.util

spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
cosim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cosim)

CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 500

# GE0.WPC* 8-bit counter bits (class-A slots, bank 1/r14 via negative disp)
WPCA = [0xe8d8, 0xe8e0, 0xe8e8, 0xe8f0, 0xe8f8, 0xe900, 0xe908, 0xe910]
# write-pipe pointer / status latch slots (from the WPC shift-register cells)
PTR = [0x76a6, 0x7b30, 0x7cb1, 0x7b33, 0x7cc6, 0x7cab, 0x7cd3, 0x7cd0,
       0x7ce2, 0x7e42, 0x7f0f, 0x7e8b, 0x7f4c, 0x7eec, 0x7fea, 0x7f31,
       0x7fa5, 0x7fef, 0x7ff7, 0x812b, 0x8144, 0x8234, 0x8288]
# LAS store-queue gather flags
GAT = [0x5082, 0xa984, 0xaa82, 0xc483, 0xae83, 0xaf83, 0xe583, 0xe683]

def main():
    m = cosim.Model("model/COSIM.m2630opt.Jul1599", "model/pin.list")
    cpu = cosim.CPU(m)
    r = cpu.run(cosim.ENTRY_INIT, max_steps=2000000)
    print("init:", r, cpu.steps)

    def setall(s, v):
        for bank in range(8):
            cpu.mem[cpu._slot_addr(s, bank)] = v

    def rd(s):
        return cpu.mem[cpu._slot_addr(s, 2)]

    # ---- inject "buffer has data" state ----
    setall(0x0c5f, 1)                       # HID2[WPE] = 1 (write-pipe enable)
    for s in range(0x6980, 0x69e0, 4):
        setall(s, 0)                        # WPAR address low bits = 0
    setall(0x6980, 1)                       # WPAR.NAN7 = 1 (BNE candidate)
    count = 24
    for i, s in enumerate(WPCA):
        setall(s, 1 if (count >> i) & 1 else 0)   # byte counter = 24 (< 32)
    for s in PTR:
        setall(s, 1)                        # write-pipe pointers/status
    for s in GAT:
        setall(s, 1)                        # gather flags

    print("start: WPC counter = %d, WPAR.NAN7(BNE?) = %d"
          % (sum(rd(s) << i for i, s in enumerate(WPCA)), rd(0x6980)))
    print("idle cycles: %d (no new stores, no bus traffic)" % CYCLES)

    changed = 0
    for cyc in range(CYCLES):
        cpu.run(cosim.ENTRY_EVAL, max_steps=10000000)
        w = sum(rd(s) << i for i, s in enumerate(WPCA))
        bne = rd(0x6980)
        ts = cpu.get_pin('TS_', 1)
        if cyc in (0, 1, 2, 10, 50, 100, 200, CYCLES - 1) or ts == 1:
            print("cyc %4d: WPC=%3d BNE=%d TS_=%d" % (cyc, w, bne, ts))
        if cyc > 2 and (w != count or bne != 1):
            changed += 1
            print("  !! cyc %d: state moved: WPC=%d BNE=%d TS_=%d" % (cyc, w, bne, ts))
            if changed > 8:
                break

    print("RESULT: %s" % (
        "state moved during idle (possible timer?)"
        if changed else
        "state frozen for %d idle cycles — no time-based flush observed "
        "(consistent with manual: no WGB timeout)" % CYCLES))

if __name__ == "__main__":
    main()
