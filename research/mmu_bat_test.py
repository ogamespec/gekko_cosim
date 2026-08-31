#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mmu_bat_test.py -- live-cycle MMU/BAT observation via the compiled model
==========================================================================
Puts the model into a "data access in progress, translation enabled" state
by injecting the internal state that the real core would produce (MSR[DR],
DBAT register contents, effective address of an in-flight load, DMM request
flags) and then runs one full per-cycle evaluation (stage 1 entry 0x1BCD60
+ stage 3 entry 0x2341CC) to see whether the DMM BAT-compare cells fire
(DMM.LBAT_HIT and friends).

Model execution model (per cycle, MVLSIM):
  * entry #2 (0x1BCD60): fast idle path; returns early at 0x1DE3A4 unless
    callblk+0x48 (slot 0x8048, the simulator's "activity" flag) is set;
    if set, continues through the assert/report tail and returns at 0x2341C8.
  * entry #3 (0x2341CC): the full netlist evaluation (combinational logic
    cones + state updates), with per-condition slice selection.

The DMM BAT-compare cell (store to DMM.LBAT_HIT at 0x302944) is gated by
slot 0xD7D0 | 0xD7D1 (bank 2) != 0; its inputs are the DBAT register words
(bank-0 slots 0x7E57/0x7E5C/0x7E5F/0x7E63), the effective-address / access
information (bank-2 LAS slots), and MSR[DR] (DMM.MSR_DR_HOLD, 0xB040).

Usage:  python3 mmu_bat_test.py [--verbose]
"""
import sys
import importlib.util

spec = importlib.util.spec_from_file_location("cosim", "cosim.py")
cosim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cosim)

VERBOSE = "--verbose" in sys.argv


def setw(cpu, slot, bank, val, width=1):
    a = cpu._slot_addr(slot, bank)
    for i in range(width):
        cpu.mem[a + i] = (val >> (8 * i)) & 0xFF


def rd(cpu, slot, bank):
    return cpu.mem[cpu._slot_addr(slot, bank)]


def rdw(cpu, slot, bank):
    a = cpu._slot_addr(slot, bank)
    return (cpu.mem[a] << 24) | (cpu.mem[a + 1] << 16) | (cpu.mem[a + 2] << 8) | cpu.mem[a + 3]


def main():
    m = cosim.Model("model/COSIM.m2630opt.Jul1599", "model/pin.list")
    cpu = cosim.CPU(m)
    r = cpu.run(cosim.ENTRY_INIT, max_steps=2000000)
    print("init: %s (%d steps)" % (r, cpu.steps))

    # ---- inject "data access in progress, DR=1, DBAT0 covers EA" ----
    cpu.mem[0x48] = 1                       # callblk+0x48: activity flag (runs stage 2+3)
    setw(cpu, 0xb040, 2, 1)                 # DMM.MSR_DR_HOLD.L1 = 1 (translation on)
    setw(cpu, 0xd840, 2, 1)                 # DMM.MSR_DR_HOLD.L2 = 1
    setw(cpu, 0xd7d0, 2, 1)                 # DMM-request gate: execute the BAT cone
    setw(cpu, 0xd7d1, 2, 1)                 # (second gate bit)
    # DBAT register words (read by the LBAT_HIT cone): all-ones = BEPI/V/PP
    # match every effective address.
    for s in (0x7e57, 0x7e5c, 0x7e5f, 0x7e63):
        setw(cpu, s, 0, 0xFFFFFFFF, 4)
    # access/EA inputs to the compare cone
    setw(cpu, 0xdc7c, 2, 0xFF, 4)           # LAS EA/access word
    setw(cpu, 0xdc84, 2, 1)                 # LAS.LMMS.BIT3.L1
    setw(cpu, 0x7d02, 1, 1)
    setw(cpu, 0xd813, 2, 1)                 # BP0.BBDU
    setw(cpu, 0x7a44, 1, 1)
    setw(cpu, 0x7e6b, 0, 1)
    setw(cpu, 0x7f57, 1, 1)
    setw(cpu, 0xa712, 2, 1)                 # L20 ...HOLD_LATCH

    def dump(tag):
        print("%s: LBAT_HIT=%d L1_BAT_HIT=%d BATMISS=%d BATMISS_L1=%d BAT_PP0=%d"
              % (tag, rd(cpu, 0x8c40, 0), rd(cpu, 0x8240, 0), rd(cpu, 0x7140, 0),
                 rd(cpu, 0x7340, 0), rd(cpu, 0xaf40, 0)))
        print("     LBAT_WI=%d LBAT_IG=%d LBAT_G=%d LBAT_LDI=%d IBAT_EN=%d DEL_DBAT=%d"
              % (rd(cpu, 0x8f40, 0), rd(cpu, 0x8d40, 0), rd(cpu, 0x8b40, 0),
                 rd(cpu, 0x8e40, 0), rd(cpu, 0x7e40, 0), rd(cpu, 0x7040, 0)))

    dump("before eval")
    print("DBAT word @0x7e57 = 0x%08x (survival check)" % rdw(cpu, 0x7e57, 0))

    r1 = cpu.run(cosim.ENTRY_EVAL, max_steps=50000000)
    print("stage1+2: %s (%d steps)" % (r1, cpu.steps))
    dump("after stage1+2")
    print("DBAT word @0x7e57 = 0x%08x" % rdw(cpu, 0x7e57, 0))

    r3 = cpu.run(0x2341cc, max_steps=100000000)
    print("stage3 (0x2341CC): %s (%d steps)" % (r3, cpu.steps))
    dump("after stage3")
    print("DBAT word @0x7e57 = 0x%08x" % rdw(cpu, 0x7e57, 0))

    if VERBOSE:
        print("asserts:", len(cpu.assert_log))
        for off, line in cpu.assert_log:
            print("  ", line)
        print("faults:", len(cpu.faults))


if __name__ == "__main__":
    main()
