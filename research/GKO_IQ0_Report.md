# GKO.IQ0 Block — Signals, Memory Elements and Native-Code Map

**Source:** `model/COSIM.m2630opt.Jul1599` (compiled MVLSIM V1.7 model of the
GKO / Gekko PowerPC-class processor).
**Extracted with:** `analyze_iq0.py` (slot/access analysis) +
`decompile_model.py` (English, patch-slot-aware decompiler).
**Companion file:** `research/GKO_IQ0_code_decompile.txt` — the decompiled
native code of the cells that handle block IQ0.
**Document version:** 1.0

---

## 1. Block identification

`GKO.IQ0` is one of the 85 top-level `GKO.<BLOCK>` logic blocks of the model.
It contributes **59 named 1-bit signals** (59 unique state slots). The name
abbreviation is read as **"Instruction Queue 0"**: every piece of structural
evidence points to the instruction-queue / fetch-status logic between the
instruction fetch path and the decode/issue logic:

* the queue status word lives in the same state region as `GKO.IC0.IFUS_REG`
  (I-Fetch **U**nit **S**tatus registers, slots `0x7b84..0x7bb8`, immediately
  adjacent to the IQ0 block);
* the cells that **write** IQ0 read the fetch side: `GKO.FIC.FIB2/FIB4/FIR9`,
  `FIM5/FIMV` (fetch instruction registers / fetch-invalid), the I-cache
  forward latches `GKO.IC0.ICAA.FWD_LAT.*`, and the L2 instruction-quadword
  latches `GKO.L20.L2DCACHEH/L.IQUAD0..3.OUTDC_L.HOLD_LATHOLD_LATCH`;
* the cells that **read** IQ0 belong to the L2 cache (IQUAD refill), the branch
  predictor (`CBB` BHT), the load-store unit (`LE0`, `LAS` fetch requests),
  the I-TLB (`IT0`) and the snoop logic (`BDR`) — i.e. the consumers of a
  fetched-instruction stream;
* the biggest single consumer is `IQWF.NAN3.L2`, read by **85 cells**
  (369 load instructions) — a heavily used queue-status/full flag.

**Chip I/O:** none of the 59 IQ0 slots lies in the pin range `0xE800..0xEB00`;
IQ0 is purely internal (no `pin.list` entries).

### 1.1 Signal families

| Family | Bits | Phase copies | Interpretation |
|--------|------|--------------|----------------|
| `IQCA` | `NAN0`, `NAN1`, `NAN3.CR` | L1+L2 | queue-status entry A (2-bit field + CR bit) |
| `IQCB` | `NAN0`, `NAN1`, `NAN3.CR` | L1+L2 (CR: L2 only) | queue-status entry B |
| `IQCC` | `NAN0`, `NAN1`, `NAN3.CR` | L1+L2 (CR: L2 only) | queue-status entry C |
| `IQCD` | `NAN0`, `NAN1`, `NAN3.CR` | L1+L2 (NAN1: L1 only) | queue-status entry D |
| `IQCE` | `NAN0`, `NAN1`, `NAN3.CR` | L1+L2 (NAN0: L1 only) | queue-status entry E |
| `IQWE` | `NAN0..NAN7`, `NBN0`, `NBN2.CR` | L1+L2 (NAN3: L1 only) | **W**rite-**E**nable bits (8-bit NAN bus + NBN bit + CR) |
| `IQWF` | `NAN0..NAN7`, `NBN0`, `NBN2.CR` | L1+L2 (NAN1: L1, NAN6: L2) | **F**ull/status bits (8-bit NAN bus + NBN bit + CR) |

`NAN`/`NBN` are the IBM DSL names of the logic cones (NAND/NOR-style
networks) whose outputs drive the bit; `NAN0..NAN7` is an 8-bit cone-output
bus. The `CR` suffix names an extra cone-output bit (a carry/result bit of
the network — its exact semantics are not decodable from the name alone) that
lives in a *different* status word than the main IQ0 block.

---

## 2. Signal inventory (all 59 signals)

Direction is derived from the native code: **R/W counts** are the numbers of
`lbz/lhz/lwz/lha` (loads) and `stb/sth/stw` (stores) instructions that touch
the slot. **Read banks / write banks** are the state-bank planes used
(bank 0 = r13 … bank 7 = r20; bank 2 = r15 is the primary output plane).

| Slot | Signal | Loads | Stores | Read banks | Write banks |
|-----:|--------|------:|-------:|:----------:|:-----------:|
| `0x007c` | `GKO.IQ0.IQCC.NAN3.CR.L2` | 6 | 2 | 0,1,2 | 0,2 |
| `0x0c7c` | `GKO.IQ0.IQCD.NAN3.CR.L2` | 1 | 1 | 1 | 0 |
| `0x407c` | `GKO.IQ0.IQWE.NBN2.CR.L2` | 1 | 1 | 1 | 0 |
| `0x4140` | `GKO.IQ0.IQCE.NAN3.CR.L1` | 1 | 1 | 1 | 0 |
| `0x7bc0` | `GKO.IQ0.IQCA.NAN1.L2` | 5 | 1 | 0,1 | 1 |
| `0x7bc4` | `GKO.IQ0.IQCA.NAN0.L2` | 5 | 2 | 0,1 | 1 |
| `0x7bcc` | `GKO.IQ0.IQCB.NAN1.L1` | 19 | 3 | 0,1 | 1 |
| `0x7bd0` | `GKO.IQ0.IQCD.NAN1.L1` | 5 | 1 | 0,1 | 1 |
| `0x7bd4` | `GKO.IQ0.IQCE.NAN0.L1` | 8 | 1 | 0,1 | 1 |
| `0x7bd8` | `GKO.IQ0.IQCD.NAN0.L1` | 2 | 1 | 0,1 | 1 |
| `0x7bdc` | `GKO.IQ0.IQCC.NAN0.L1` | 10 | 3 | 0,1 | 1 |
| `0x7be0` | `GKO.IQ0.IQCE.NAN1.L1` | 13 | 4 | 0,1 | 1 |
| `0x7be4` | `GKO.IQ0.IQCB.NAN0.L1` | 10 | 5 | 0,1 | 1 |
| `0x7be8` | `GKO.IQ0.IQCC.NAN1.L1` | 9 | 1 | 0,1 | 1 |
| `0x7bec` | `GKO.IQ0.IQCB.NAN1.L2` | 10 | 1 | 0,1 | 1 |
| `0x7bf0` | `GKO.IQ0.IQCB.NAN0.L2` | 8 | 2 | 0,1 | 1 |
| `0x7bf8` | `GKO.IQ0.IQCC.NAN1.L2` | 8 | 7 | 0,1 | 1 |
| `0x7bfc` | `GKO.IQ0.IQCC.NAN0.L2` | 3 | 1 | 0,1 | 1 |
| `0x7c08` | `GKO.IQ0.IQCD.NAN0.L2` | 4 | 1 | 0,1 | 1 |
| `0x7c10` | `GKO.IQ0.IQCE.NAN1.L2` | 4 | 1 | 1 | 1 |
| `0x7c1c` | `GKO.IQ0.IQWE.NAN0.L2` | 21 | 4 | 0,1 | 1 |
| `0x7c20` | `GKO.IQ0.IQWE.NAN2.L2` | 21 | 3 | 0,1 | 1 |
| `0x7c28` | `GKO.IQ0.IQWE.NAN4.L2` | 4 | 1 | 0,1 | 1 |
| `0x7c2c` | `GKO.IQ0.IQWE.NAN5.L2` | 15 | 2 | 0,1 | 1 |
| `0x7c30` | `GKO.IQ0.IQWE.NAN6.L2` | 17 | 2 | 0,1 | 1 |
| `0x7c34` | `GKO.IQ0.IQWE.NAN7.L2` | 23 | 2 | 0,1 | 1 |
| `0x7c38` | `GKO.IQ0.IQWE.NBN0.L2` | 17 | 2 | 0,1 | 1 |
| `0x7c3c` | `GKO.IQ0.IQWE.NAN1.L2` | 21 | 2 | 0,1 | 1 |
| `0x7c44` | `GKO.IQ0.IQWF.NAN3.L2` | 369 | 38 | 0,1 | 1 |
| `0x7c48` | `GKO.IQ0.IQWF.NAN4.L2` | 20 | 2 | 0,1 | 1 |
| `0x7c4c` | `GKO.IQ0.IQWF.NAN5.L2` | 20 | 2 | 0,1 | 1 |
| `0x7c50` | `GKO.IQ0.IQWF.NAN6.L2` | 13 | 2 | 0,1 | 1 |
| `0x7c54` | `GKO.IQ0.IQWF.NAN7.L2` | 13 | 2 | 0,1 | 1 |
| `0x7c58` | `GKO.IQ0.IQWF.NAN2.L2` | 13 | 2 | 0,1 | 1 |
| `0x7c5c` | `GKO.IQ0.IQWF.NBN0.L2` | 12 | 2 | 0,1 | 1 |
| `0x7c60` | `GKO.IQ0.IQWF.NAN0.L2` | 12 | 2 | 0,1 | 1 |
| `0x7c70` | `GKO.IQ0.IQWF.NAN5.L1` | 18 | 1 | 0,1 | 1 |
| `0x7c74` | `GKO.IQ0.IQWF.NAN4.L1` | 18 | 1 | 0,1 | 1 |
| `0x7c78` | `GKO.IQ0.IQWF.NAN3.L1` | 18 | 1 | 0,1 | 1 |
| `0x7c7c` | `GKO.IQ0.IQWF.NAN2.L1` | 11 | 1 | 0,1 | 1 |
| `0x7c80` | `GKO.IQ0.IQWF.NAN1.L1` | 11 | 1 | 0,1 | 1 |
| `0x7c84` | `GKO.IQ0.IQWF.NAN0.L1` | 18 | 1 | 0,1 | 1 |
| `0x7c88` | `GKO.IQ0.IQWE.NBN0.L1` | 18 | 1 | 0,1 | 1 |
| `0x7c8c` | `GKO.IQ0.IQCA.NAN0.L1` | 5 | 2 | 0,1 | 1 |
| `0x7c90` | `GKO.IQ0.IQCA.NAN1.L1` | 10 | 6 | 0,1 | 1 |
| `0x7c94` | `GKO.IQ0.IQWE.NAN7.L1` | 5 | 2 | 0,1 | 1 |
| `0x7c98` | `GKO.IQ0.IQWE.NAN6.L1` | 2 | 1 | 0,1 | 1 |
| `0x7c9c` | `GKO.IQ0.IQWE.NAN5.L1` | 8 | 1 | 0,1 | 1 |
| `0x7ca0` | `GKO.IQ0.IQWE.NAN4.L1` | 2 | 1 | 0,1 | 1 |
| `0x7ca4` | `GKO.IQ0.IQWE.NAN3.L1` | 4 | 1 | 0,1 | 1 |
| `0x7ca8` | `GKO.IQ0.IQWE.NAN2.L1` | 22 | 5 | 0,1 | 1 |
| `0x7cac` | `GKO.IQ0.IQWE.NAN1.L1` | 50 | 1 | 0,1 | 1 |
| `0x7cb0` | `GKO.IQ0.IQWF.NBN0.L1` | 27 | 10 | 0,1 | 1 |
| `0x7cb4` | `GKO.IQ0.IQWE.NAN0.L1` | 2 | 1 | 0,1 | 1 |
| `0x7cb8` | `GKO.IQ0.IQWF.NAN7.L1` | 44 | 6 | 0,1 | 1 |
| `0x7d7b` | `GKO.IQ0.IQCA.NAN3.CR.L1` | 3 | 1 | 1 | 1 |
| `0x817b` | `GKO.IQ0.IQWF.NBN2.CR.L1` | 18 | 2 | 2 | 2 |
| `0xc87b` | `GKO.IQ0.IQCA.NAN3.CR.L2` | 2 | 1 | 1,2 | 3 |
| `0xf47b` | `GKO.IQ0.IQCB.NAN3.CR.L2` | 12 | 1 | 0,1,2 | 2 |

Totals: **1,071 loads, 159 stores** across all IQ0 slots — the IQ0 signals
are read ~7× more often than they are written, as expected for latched
queue-status flags that are fanned out to many consumers.

> **Slot addressing** (spec §7.1/§11): the *slot* is the offset inside any
> state bank; `slot = disp` for `disp ≥ 0`, `slot = disp + 0x10000` for
> `disp < 0`. All IQ0 stores use positive displacements through **r14
> (bank 1)**; reads use **r13 (bank 0)** and r14 (bank 1). The `CR` bits are
> read via banks 1–2 and written via banks 0–3, i.e. they are maintained in
> additional planes.

---

## 3. Internal memory elements

In this compiled model every wire slot *is* a storage element (one byte per
wire, two-value logic, 8 bank copies). The IQ0 memory elements are:

### 3.1 L1/L2 latch-pair planes
Each logical IQ0 signal exists as an **L1 and/or L2 phase copy** (separate
slots); the pairs are the queue's latches:

| Signal | L1 slot | L2 slot | Complete pair? |
|--------|:-------:|:-------:|:--------------:|
| `IQCA.NAN0` | `0x7c8c` | `0x7bc4` | ✔ |
| `IQCA.NAN1` | `0x7c90` | `0x7bc0` | ✔ |
| `IQCB.NAN0` | `0x7be4` | `0x7bf0` | ✔ |
| `IQCB.NAN1` | `0x7bcc` | `0x7bec` | ✔ |
| `IQCC.NAN0` | `0x7bdc` | `0x7bfc` | ✔ |
| `IQCC.NAN1` | `0x7be8` | `0x7bf8` | ✔ |
| `IQCD.NAN0` | `0x7bd8` | `0x7c08` | ✔ |
| `IQCD.NAN1` | `0x7bd0` | — (L1 only) | ✖ |
| `IQCE.NAN0` | `0x7bd4` | — (L1 only) | ✖ |
| `IQCE.NAN1` | `0x7be0` | `0x7c10` | ✔ |
| `IQWE.NAN0..7` | `0x7cb4..0x7c94` | `0x7c1c..0x7c34` | NAN3: L1 only |
| `IQWE.NBN0` | `0x7c88` | `0x7c38` | ✔ |
| `IQWF.NAN0..7` | `0x7c84..0x7cb8` | `0x7c60..0x7c54` | NAN1: L1, NAN6: L2 |
| `IQWF.NBN0` | `0x7cb0` | `0x7c5c` | ✔ |
| `CR` bits (8) | `0x7d7b`, `0x4140`, `0x817b` | `0x007c`, `0x0c7c`, `0x407c`, `0xc87b`, `0xf47b` | one phase each |

The phase planes are the queue's **register/latch storage**: cells write the
L1 copy (bank 1) from the L2 copy of the previous cycle or from new values,
and the L2 copy is what downstream logic reads.

### 3.2 True latch (self-feedback) cells
Six cells both load and store the **same** IQ0 slot — the model's explicit
hold/register pattern:

| Cell | Signal | Pattern |
|------|--------|---------|
| `0x03f180` | `IQWE.NAN0.L2` | `Q <= (new & en) | (Q & ~en)`-style hold |
| `0x075780` | `IQCA.NAN0.L2` | self-feedback |
| `0x0cc880` | `IQCA.NAN1.L1` | self-feedback |
| `0x0f4b00` | `IQCA.NAN1.L1` | self-feedback |
| `0x130400` | `IQWF.NAN7.L1` | self-feedback |
| `0x1e8280` | `IQCA.NAN1.L1` | self-feedback |

### 3.3 Packed 32-bit status words
The IQ0 signals are the *named bits* of wider state words. Typical writer
cells store a whole row of adjacent slots with one `stb`/`stw` each — e.g.
cell `0x02a880` writes slots `0x7bbb..0x7bc1` (7 wires: `0x7bc0` =
`IQCA.NAN1.L2` + 6 unnamed neighbours); cell `0x02e780` issues a `stw` at
`0x2e7c0` storing the 32-bit word at `0x7c8c` (`IQCA.NAN0.L1` is the most
significant byte of it). The unnamed
neighbour slots (`0x7b80..0x7d00` region) are the remaining bits of the
queue-status words. The actual **instruction data** itself is not in the
named-wire space: the model keeps array data (caches/buffers) in its array
memory (call-block + `0x3F9AAC`, spec §5.6), which `cosim.py` models as
zeros; the 59 named IQ0 wires are the queue's control/status view.

---

## 4. Input signals (drivers of the IQ0 logic)

The **inputs of block IQ0** are all wires *loaded* by the 118 cells that
*write* an IQ0 slot (the IQ0 output logic). There are **231 named signals
from 55 blocks plus 645 unnamed slots**; the named ones, by source block
(sorted by count):

| Block | # | Representative signals (block role) |
|------:|--:|-------------------------------------|
| `L20` | 24 | `L2DCACHEH/L.IQUAD0..3.OUTDC_L.HOLD_LATHOLD_LATCH` (L2 **I**NSTRUCTION **QUAD**WORD data latches), `L2DB.NAN1`, `L2DCACHEL.I43.*` — the fetched-instruction data path |
| `IC0` | 18 | `ICAA.FWD_LAT.L2.RRAM_0_HOLDL2` (I-cache forward latches / redundancy hold), `IFUS_REG.*` (I-fetch-unit status) |
| `LAS` | 18 | `LXFA/LXAA/LXCA/LXFA`, `CSQ_ADDR/CSQ_MBIT/CSQ_BYTE`, `FDQ_PQA`, `HQ_ST_BEN`, `FSQ_BYTE`, `BAC_STWCX_DONE_LAT` (LSU fetch/queue control) |
| `JTC` | 14 | `DIAGLAT*`, `LSRLL1`, `WAKEUPCALL_SYNC1`, `RUNNCOUNTER*`, `ICACHE_DIAG`, `LOCK_GCLK2HLD`, `CLRLAT1`, `BIST11` (JTAG/LSSD diagnostics, BIST, clocks) |
| `CCC` | 12 | `RNBUFF0..5` (rename buffers), `TYPE1/TYPE5`, `FLT_IDN`, `VALID4DUP`, `CBB_UBR_LATCH`, `FPIP`, `FREEZE_LATCH` (completion/flush control) |
| `BP0` | 11 | `BBFB/BBGE/BBDO/BBBD/BBDK/BBDM/BBDG/BBEB/BBCM/BBHM`, `OEBL` (bus driver slices / output enables) |
| `BD0` | 8 | `BDBE.NAN4/NAN5`, `BDCA.NAN0/3/4`, `BDBF.NAN0/1` (bus data driver) |
| `BDR` | 7 | `RUNQ_LAT3/6/8`, `RLD_LAT3`, `STKY_FAIL_0_8`, `L2OCD_LAT3` (bus data return / run queues) |
| `CBB` | 7 | `UBR1_CR_NIB_SEL`, `VALID.BIT3`, `CBB_BHT_WR1_DATA/WR0_ADDR`, `BIST_BTIC_COMPARE`, `PERF`, `IGNORE` (branch predictor / BHT) |
| `GE0` | 6 | `WPCA/WPCB`, `HID_G_REG`, `QNTR3` (global/SPR + queue counters) |
| `CDC` | 6 | `REGOP_4`, `FRNM0`, `FREGOP_0`, `GRNM0`, `GWB1`, `DOZE_LATCH` (chip/power control) |
| `DMM` | 5 | `DM0_VALID1`, `LBAT_HIT`, `LBAT_G`, `GRAPH_HOLD`, `SDR1_RD` (data MMU / BAT) |
| `BAC` | 5 | `SNPI_LAT10/6`, `DLD_BSY_DELAY`, `PFM_LAT1`, `L2CST1_LAT` (bus address control / snoop) |
| `FIC` | 5 | `FIB2.BIT4`, `FIR9.BIT1`, `FIB4.BIT0`, `FIM5.BIT0`, `FIMV.BIT1` (**instruction fetch** registers / fetch-invalid) |
| `QSR` | 5 | `TSCC/TSCL/TSCX/TSCS/TSCN` (queue/status registers) |
| `FWN` | 4 | `FWNK/FWNO/FWSU/FWN7` (FPU write-back network) |
| `XEB` | 4 | `XEJC2`, `XEIJ2`, `XEBC`, `XEFD2` (integer execution unit B) |
| `LLC` | 4 | `LHA_SEL_PRE_M`, `LAC_MULTS_GPR_M`, `SSCALE_H` (D-cache access arbiter) |
| `DLS` | 4 | `SBW`, `MISS_WHILE_DMA`, `DVAL`, `INT_PEND` (D-cache ops/state) |
| others (36 blocks) | ~85 | `BTC` (L2DHIT, READ_CAPTURE, BIST_DATA), `CB0/CB1/CB3` (completion buffers), `DQC/DQ0` (data queues), `IT0` (I-TLB LRU/tag), `HW0/HE0/HI0/HI1/HIC/HA0` (arrays/slices), `MM0` (MMU arrays), `DA0/DAE/LA0` (address), `TWC/TM0/CSC` (timers/thermal), `FDC/FDL/FI0/FI1/FWC/FW0` (FPU/decode), `LQU/LS0/LQ0`, `XEA`, `XXA`, `WA0` (ECID)… |

The largest *unnamed* input groups are the slots `0x74xx..0x77xx` and
`0x7cxx..0x7exx` (bank 0/1) — the un-named bits of the same status-word rows
that IQ0 belongs to — plus `0x0xxx..0x1xxx` and `0xE7xx..0xFxxx` (bank 1)
carrying decode/bus side data.

### 4.1 Typical input logic
The writer cells are combinational cones / muxes over these inputs. Example
(cell `0x02a880`, from the decompiled file):

```
w[1][0x7bc0] <= ((w[0][0x01fc] & ~r28) | (w[0][0x027c] & r28));   // GKO.IQ0.IQCA.NAN1.L2
```

i.e. `IQCA.NAN1.L2` is a two-way mux of bank-0 wires selected by an enable —
the standard latch-update form (hold old value vs. load new value).

---

## 5. Output signals (consumers of the IQ0 logic)

All 59 IQ0 signals are written by the model, so all of them are *outputs* of
the IQ0 logic, consumed by **624 reader-only cells plus 118 writer cells**
(742 cells in total touch IQ0). Main consumers by block:

| Consumer | Signals read | Cells |
|----------|--------------|------:|
| `LE0` (load-execution datapath) | `IQCA/IQCB/IQCC/IQCD/IQCE NAN*`, `IQWE/IQWF NAN*` | many (e.g. 4–5 cells each) |
| `L20` (L2 cache) | `IQWF.NAN3.L2` (9+3+3 loads), `IQWE/IQWF` bits | ~30 |
| `IC0` (I-cache) | `IQWF.NAN3/4/0`, `IQWE.NBN0/1/2`, `IQCB.NAN0` | ~20 |
| `LAS` (LSU) | `IQCA.NAN0`, `IQCD.NAN0/1`, `IQWF.NAN5` | ~10 |
| `DMM` (data MMU) | `IQCC.NAN0`, `IQCA.NAN1`, `IQWE.NAN2`, `IQWF.NBN0` | ~10 |
| `BP0` (bus driver) | `IQCB.NAN0`, `IQCD.NAN0`, `IQWE.NAN0`, `IQWF.NAN0/NBN2.CR` | ~8 |
| `BDR` (bus data return) | `IQWF.NAN7/NAN2/NBN0`, `IQWF.NBN2.CR` | ~8 |
| `BDT` (bus data transfer) | `IQWF.*`, `IQWF.NBN2.CR` | ~4 |
| `FIC` (instruction fetch) | `IQCB.NAN3.CR.L2` | 2 |
| `CBB` (BHT/BTIC) | `IQWF.NAN0/NAN3`, `IQWF.NBN2.CR` | ~3 |
| `JTC` (JTAG/test) | `IQCC.NAN1`, `IQWE.NAN1`, `IQCA.NAN3.CR.L2` | ~5 |
| `IT0` (I-TLB) | `IQWF.NAN7` | ~3 |
| `HE0/GE0/CSC/ICC/XD0/HI1/HA0/QAB/XM0/FE0/HW0/TWC/PL0…` | various | 1–2 each |

**Hot signal:** `GKO.IQ0.IQWF.NAN3.L2` (slot `0x7c44`) is the most fanned-out
IQ0 wire — 369 loads in 85 cells, including the 18-cell timing chain at
`0x1e3180..0x1e3a00` (254 loads of this one wire interleaved with
`or r25,r25,r24` dependency pads, no functional stores — a compiled timing/
delay chain) and the L2-cache consumer cluster at `0x1ec380..0x1ed700`
(120 loads, drives `L2DCACHEL.IQUAD*.HOLD_LATHOLD_LATCH` and `CBB_BHT_WR1_ADDR`).

---

## 6. Native-code map (where IQ0 is handled)

The model code is a flat sequence of 0x80-byte evaluation cells; a cell
"handles" IQ0 if any of its instructions accesses an IQ0 slot. **742 cells
touch IQ0: 118 writer cells + 624 reader-only cells.**

### 6.1 Writer cells (the IQ0 output logic) — 79 runs / 118 cells

| Cell run (start..end) | # cells | IQ0 signals written |
|-----------------------|--------:|---------------------|
| `0x02a880..0x02a900` | 2 | IQCA.NAN1.L2, IQCA.NAN0.L2 |
| `0x02aa00..0x02ad00` | 7 | IQCB.NAN1.L1, IQCD.NAN1.L1, IQCE.NAN0.L1, IQCC.NAN0.L1, IQCE.NAN1.L1, IQCB.NAN0.L1, IQCB.NAN1.L2, IQCC.NAN1.L1, IQCB.NAN0.L2 |
| `0x02ae80..0x02af00` | 2 | IQCC.NAN1.L2, IQCC.NAN0.L2 |
| `0x02b080..0x02b080` | 1 | IQCE.NAN1.L2 |
| `0x02b480..0x02b480` | 1 | IQWE.NAN0.L2 |
| `0x02b580..0x02b580` | 1 | IQWE.NAN2.L2 |
| `0x02b780..0x02b780` | 1 | IQWE.NAN4.L2 |
| `0x02bd80..0x02bd80` | 1 | IQWE.NAN5.L2 |
| `0x02c180..0x02c180` | 1 | IQWE.NAN6.L2 |
| `0x02c500..0x02c500` | 1 | IQWE.NAN7.L2 |
| `0x02d080..0x02d080` | 1 | IQWE.NBN0.L2 |
| `0x02d400..0x02d400` | 1 | IQWE.NAN1.L2 |
| `0x02e380..0x02e500` | 4 | IQWF.NAN3.L2, IQWF.NAN4.L2, IQWF.NAN5.L2, IQWF.NAN6.L2, IQWF.NAN2.L2, IQWF.NAN7.L2, IQWF.NBN0.L2, IQWF.NAN0.L2 |
| `0x02e600..0x02ea00` | 9 | IQWF.NAN4.L1, IQWF.NAN5.L1, IQWF.NAN2.L1, IQWF.NAN3.L1, IQWE.NBN0.L1, IQWF.NAN0.L1, IQWF.NAN1.L1, IQCA.NAN0.L1, IQCA.NAN1.L1, IQWE.NAN7.L1, IQWE.NAN5.L1, IQWE.NAN2.L1, IQWE.NAN3.L1, IQWE.NAN1.L1 |
| `0x02f180..0x02f180` | 1 | IQWF.NBN0.L1 |
| `0x02f300..0x02f300` | 1 | IQWF.NAN7.L1 |
| `0x03f000..0x03f000` | 1 | IQCB.NAN0.L2 |
| `0x03f180..0x03f200` | 2 | IQWE.NAN0.L2, IQWE.NAN2.L2 |
| `0x040000..0x040000` | 1 | IQWF.NAN3.L2 |
| `0x041380..0x041380` | 1 | IQWF.NBN2.CR.L1 |
| `0x05b100..0x05b400` | 7 | IQWF.NAN3.L2 |
| `0x06d480..0x06d480` | 1 | IQWF.NBN2.CR.L1 |
| `0x075780..0x075780` | 1 | IQCA.NAN0.L2 |
| `0x075e00..0x075e00` | 1 | IQWF.NAN3.L2 |
| `0x083080..0x083080` | 1 | IQWF.NAN3.L2 |
| `0x0c9080..0x0c9080` | 1 | IQCC.NAN0.L1 |
| `0x0cc880..0x0cc880` | 1 | IQCA.NAN1.L1 |
| `0x0d4900..0x0d4900` | 1 | IQWE.NAN7.L1 |
| `0x0df200..0x0df200` | 1 | IQCB.NAN0.L1 |
| `0x0e2700..0x0e2700` | 1 | IQCA.NAN1.L1 |
| `0x0e8200..0x0e8280` | 2 | IQWE.NAN5.L2, IQWE.NAN6.L2, IQWE.NAN7.L2, IQWE.NBN0.L2 |
| `0x0e8c80..0x0e8c80` | 1 | IQWE.NAN1.L2 |
| `0x0e9680..0x0e9680` | 1 | IQWE.NAN0.L2 |
| `0x0e9f80..0x0e9f80` | 1 | IQWE.NAN2.L2 |
| `0x0ecd00..0x0ecd80` | 2 | IQCE.NAN1.L1, IQCB.NAN0.L1 |
| `0x0f1800..0x0f1800` | 1 | IQWF.NBN0.L1 |
| `0x0f3580..0x0f3580` | 1 | IQWF.NAN7.L1 |
| `0x0f4b00..0x0f4b00` | 1 | IQCA.NAN1.L1 |
| `0x0fbc00..0x0fbc00` | 1 | IQCA.NAN1.L1 |
| `0x10e580..0x10e580` | 1 | IQCA.NAN0.L1 |
| `0x11aa00..0x11aa00` | 1 | IQCC.NAN1.L2 |
| `0x11b200..0x11b200` | 1 | IQCB.NAN1.L1 |
| `0x127080..0x127080` | 1 | IQCB.NAN0.L1, IQCE.NAN1.L1 |
| `0x130400..0x130400` | 1 | IQWF.NAN7.L1 |
| `0x143700..0x143700` | 1 | IQCB.NAN3.CR.L2 |
| `0x146f80..0x146f80` | 1 | IQCB.NAN1.L1 |
| `0x153000..0x153000` | 1 | IQCC.NAN1.L2 |
| `0x153a00..0x153a00` | 1 | IQWE.NAN2.L1 |
| `0x153c00..0x153c00` | 1 | IQWF.NBN0.L1 |
| `0x162300..0x162300` | 1 | IQWF.NAN7.L1 |
| `0x175480..0x175480` | 1 | IQCA.NAN3.CR.L2 |
| `0x17a380..0x17a380` | 1 | IQCC.NAN1.L2 |
| `0x17a500..0x17a500` | 1 | IQCC.NAN1.L2 |
| `0x17a700..0x17a700` | 1 | IQCC.NAN1.L2 |
| `0x17a800..0x17a800` | 1 | IQCC.NAN1.L2 |
| `0x17a900..0x17a980` | 2 | IQWF.NBN0.L1 |
| `0x17aa80..0x17ab00` | 2 | IQWF.NBN0.L1 |
| `0x185700..0x185780` | 2 | IQWE.NAN2.L1, IQWF.NBN0.L1 |
| `0x1a1980..0x1a1980` | 1 | IQCC.NAN3.CR.L2 |
| `0x1a5680..0x1a5680` | 1 | IQCA.NAN3.CR.L1 |
| `0x1a8200..0x1a8200` | 1 | IQWF.NAN7.L1 |
| `0x1b3900..0x1b3900` | 1 | IQCE.NAN1.L1 |
| `0x1b4d00..0x1b4d00` | 1 | IQCB.NAN0.L1 |
| `0x1b5580..0x1b5580` | 1 | IQWF.NAN7.L1 |
| `0x1bc600..0x1bc600` | 1 | IQWE.NAN2.L1, IQWF.NBN0.L1 |
| `0x1df800..0x1df800` | 1 | IQCC.NAN0.L1 |
| `0x1dfa00..0x1dfa80` | 2 | IQWE.NAN2.L1, IQWF.NBN0.L1 |
| `0x1e8280..0x1e8280` | 1 | IQCA.NAN1.L1 |
| `0x245e00..0x245e00` | 1 | IQCD.NAN3.CR.L2 |
| `0x2f6e80..0x2f6e80` | 1 | IQWE.NBN2.CR.L2 |
| `0x2f7900..0x2f7900` | 1 | IQCE.NAN3.CR.L1 |
| `0x350b00..0x350b00` | 1 | IQCD.NAN0.L2 |
| `0x36d100..0x36d100` | 1 | IQWE.NAN4.L1 |
| `0x373e80..0x373e80` | 1 | IQCD.NAN0.L1 |
| `0x37c580..0x37c880` | 7 | IQWE.NAN0.L2, IQWF.NAN3.L2, IQWF.NAN4.L2, IQWF.NAN5.L2, IQWF.NAN6.L2, IQWF.NAN7.L2, IQWF.NAN2.L2 |
| `0x37c980..0x37ca00` | 2 | IQWF.NBN0.L2, IQWF.NAN0.L2 |
| `0x44f380..0x44f380` | 1 | IQCC.NAN3.CR.L2 |
| `0x483d00..0x483d00` | 1 | IQWE.NAN6.L1 |
| `0x485700..0x485700` | 1 | IQWE.NAN0.L1 |


### 6.2 Reader-only clusters (consumers)
Biggest reader-only runs (see §5): `0x1e3180..0x1e3a00` (18 cells, timing
chain on `IQWF.NAN3.L2`), `0x1ec380..0x1ed700` (39 cells, L2 refill/BHT),
`0x1eee80..0x1ef300` (10 cells), `0x1ecc00..0x1ed700` (23 cells),
`0x2fea00..0x300c00` (18 cells, LAS/HA0 fetch requests), `0x0f1c00..0x0f2080`
(10 cells, I-TLB/snoop), `0x235600..0x235780` (4 cells — conditional fan-out
of the whole queue status into `LE0`/`LAS`/`BP0` registers), plus ~40 smaller
runs of 3–6 cells.

### 6.3 Structural notes
* **Cell size:** every cell is 0x80 bytes (32 words); its first word is a
  patch-list node (0x60000000 = `nop` after loading). 1,024 of the 38,738
  nodes deviate from strict 0x80 *alignment* (they still step by 0x80);
  741 of the 742 IQ0 cells sit at aligned seams — the only exception is the
  reader cell at `0x1FED00` (one `IQWF.NAN3.L2` load at `0x1fed28`), whose
  true seam is the misaligned node at `0x1FED08`.
* **Latch rows:** one writer cell usually updates a *row* of adjacent slots
  (e.g. `0x02a880` writes 7 wires `0x7bbb..0x7bc1`), which is how the
  compiled netlist packs related status bits.
* **Status-word copies:** the CR-bit cells (`0x245e00`, `0x2f6e80`,
  `0x2f7900`, `0x175480`) copy/clear multi-byte status words that contain one
  IQ0 CR bit each.

---

## 7. Decompiled code

`research/GKO_IQ0_code_decompile.txt` contains the decompiled native code of
**182 cells**: all 118 writer cells (the IQ0 output logic) plus the exact
cells of the selected consumer clusters (`0x235600..0x235780`,
`0x1ec380..0x1ed700`, `0x2fea00..0x300c00`, `0x0f1c00..0x0f2080`), in
address order. Example (cell `0x02a880`):

```
// ========== IQ0 output cell 0x02a880 (writes: GKO.IQ0.IQCA.NAN1.L2): 0x2a880..0x2a900 ==========
// @0002a880: [patch slot] nop
// @0002a8e4:  w[1][7bc0]    <= ((w[0][01fc] & ~(r28)) | (w[0][027c] & r28));  // GKO.IQ0.IQCA.NAN1.L2
```

Regenerate with:
```
python3 analyze_iq0.py --decompile research/GKO_IQ0_code_decompile.txt
```

---

## 8. Methodology

1. **Symbol table** — parsed from the model (`0x4BA840`, 0x5B76C bytes,
   classes A/B, prefix-compressed names) by `cosim.Model._symbols`; all names
   starting with `GKO.IQ0.` were collected (59 slots).
2. **Access scan** — the whole code region `0x0..0x4BA840` was predecoded
   with the `cosim.py` decoder (patch nodes → nop). Every load/store through
   the state-bank pointers r13..r20 was mapped to its slot; IQ0 accesses were
   tallied per slot and per 0x80-byte cell.
3. **Classification** — slots are written by model cells (159 stores) and
   read by consumers (1,071 loads); inputs = non-IQ0 wires loaded in writer
   cells; internal memory = L1/L2 pairs, self-feedback cells, packed words.
4. **Decompilation** — `decompile_model.py` (this repository, English,
   patch-slot aware) symbolically executes each cell and prints
   Verilog-style assignments; `analyze_iq0.py --decompile` drives it over the
   IQ0 cells.

## 9. References

* `COSIM_m2630opt_SPEC.md` — compiled-model file format (slots §7.1, planes
  §11, cells §4, arrays §5.6).
* `research/GKO_BLOCKS.md` — block inventory (IQ0 listed under "remaining
  blocks").
* `research/GKO_IQ0_code_decompile.txt` — decompiled IQ0 cells.
* `analyze_iq0.py`, `decompile_model.py` — tools used (repo root).
* `model/COSIM.m2630opt.Jul1599.names.txt` — slot→name map.
