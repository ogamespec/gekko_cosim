# Gekko MMU and BAT — Research Report

**Subject:** the memory-management unit (MMU) and block-address-translation
(BAT) mechanism of the Gekko microprocessor (GameCube CPU, MPC750-class
core): architecture, model implementation, and disassembled netlist regions.
**Sources:** IBM Gekko RISC Microprocessor User Manual (Version 1.2, 5/25/00,
Chapter 5 "Memory Management"), the compiled logic model
`model/COSIM.m2630opt.Jul1599` (MVLSIM), the disassembler/decompiler tools.
**Document version:** 2.0

---

## 1. Executive summary

1. Gekko implements **two MMUs** (IMMU and DMMU) that operate **in
   parallel**; the instruction and data **TLBs are separate, 128-entry,
   two-way set-associative, with LRU replacement**, and are
   **hardware-reloadable** (the page-table search is performed in hardware).
2. Translation flow (manual §5.1): real-addressing mode when disabled
   (`MSR[IR]=0` for I, `MSR[DR]=0` for D) → **BAT compare** (4 IBAT + 4
   DBAT pairs) → **segment descriptor** (16 on-chip segment registers;
   Gekko does not implement direct-store, T=1 segments fault) → **page
   table** (hash search via **SDR1**) → TLB.
3. In the model the MMU/BAT logic is spread over the blocks:
   * `IT0` — the **I-TLB tag array** (`ITAA`: index, LRU, tag write,
     `icbi`),
   * `ICC` — instruction-side MMU/cache control (**`ITLB_HIT`**,
     **`LIBAT_WIMG`** — I-BAT WIMG),
   * `DMM` — **data MMU control** (`L1_TLB_HIT`, `LBAT_HIT`,
     `LBAT_WI/IG/G` — D-BAT WIMG, `L1_DM0_LRU`, `tlbie`),
   * `MM0` — the **MMU data arrays** (`DMBA..DMX*` — translation entries,
     `BIST_ADDR`),
   * `DAE` — **data address translation** (`SIZE_WIM`, `ST_RID`/`LD_RID`,
     `MISS_CSE`/`SNP_CSE`/`DMA_CSE`),
   * `TWC` — the **translation-walk controller** (hardware page-table
     walker: `PTE_MATCH`, `ITW_OP`, `PF_ITW_START`/`PF_DTW_START`,
     `NO_ENTRY_D`),
   * `CSC` — the **system-register unit** (`ACSDR1`, `ACCDAR`, `ACCBAT`,
     `IBATS`, `DSISR`, time base/decrementer).
4. **Per-cycle execution of the model is a two-call flow**: entry #2
   (`0x1BCD60`) runs the fast idle path and returns early at `0x1DE3A4`
   unless the simulator's activity flag (call block +0x48, slot `0x8048`)
   is set; if set it runs an assert/report tail and returns at `0x2341C8`.
   Entry #3 (`0x2341CC`) then evaluates the **full netlist** (all
   combinational cones with per-condition slice selection) up to the final
   return at `0x4BA83C`.  All MMU/BAT/TWC cells live in entry #3 (or in the
   init pass), which is why they were invisible in earlier per-cycle runs.
5. **`TWC.PTE_MATCH` is an external (simulator-provided) input**: the whole
   model code contains no store to its slots (`0x1FED`/`0x63ED`), only
   loads.  The page-table-entry comparison is therefore performed outside
   the compiled model (the MVLSIM "ppc"-type core/testbench), while the
   walk **state machine** (`TWCZ/TWC*` bits) is internal.
6. **Live-cycle probing works**: by injecting the "data access in
   progress" state (activity flag, `MSR_DR_HOLD`, DBAT register words, DMM
   request gate `0xD7D0|0xD7D1`) and running entry #3, the DMM BAT-compare
   cell executes and **`DMM.LBAT_HIT` asserts 0→1** in a live cycle
   (`mmu_bat_test.py`); the control run without the gate stays 0.

## 2. Architecture (IBM Gekko User Manual, Chapter 5)

### 2.1 Address translation flow (§5.1)

```
Effective address generated
  |-- MSR[IR]/[DR] = 0  ->  real addressing mode (physical = effective)
  |-- compare with the I-/D- BAT array:
  |      hit  -> translate, qualify with block protection (else ISI/DSI)
  |      miss -> locate the segment descriptor (EA[0:3] selects one of
  |              16 segment registers; T bit selects page / direct-store)
  |      page -> perform page-table search (hardware) -> TLB -> translate
  |      direct-store (T=1) -> Gekko does NOT implement it -> DSI/ISI
  `-- no valid PTE and no BAT hit -> page fault -> ISI / DSI
```

Translation exceptions (manual Table 5-3):

| Condition | I-access | D-access |
|-----------|----------|----------|
| Page fault (no PTE, no BAT) | ISI, SRR1[1]=1 | DSI, DSISR[1]=1 |
| Block protection violation | ISI, SRR1[4]=1 | DSI, DSISR[4]=1 |
| Page protection violation | ISI, SRR1[4]=1 | DSI, DSISR[4]=1 |
| No-execute (SR[N]=1) fetch | ISI, SRR1[3]=1 | — |
| Fetch from direct-store segment (SR[T]=1) | ISI, SRR1[3]=1 | — |

### 2.2 BAT (§5.3)

* 4 **IBAT** pairs (`IBAT0U..IBAT3U` with `IBAT0L..IBAT3L`) and 4 **DBAT**
  pairs (`DBAT0U..DBAT3U` with `DBAT0L..DBAT3L`), 32-bit SPRs accessed by
  `mtspr`/`mfspr`; maps large ranges (≥ one page) to contiguous physical
  memory (e.g. a memory-mapped display buffer).
* A BAT hit is qualified with the block protection; violation → ISI/DSI.
* **Gekko's BAT registers are not initialized by hardware reset.**
* BAT block sizes and WIMG attributes are carried in the upper/lower BAT
  registers (the fields are defined in the Programming Environments manual;
  in the model the WIMG bits appear as `LBAT_WI/IG/G` (D) and `LIBAT_WIMG`
  (I)).

### 2.3 TLB (§5.4.3)

* **Separate 128-entry data and instruction TLBs** (the two MMUs operate in
  parallel; some resources shared, some shadowed per MMU); two-way
  set-associative, LRU replacement.
* **Hardware-reloadable**: on a miss the processor performs the page-table
  search itself (hash function over VSID + page index, two PTE groups per
  hash, primary/secondary), then fills the TLB and re-runs the access.
* R/C (referenced/changed) bit maintenance follows the model of Table 5-8
  (Gekko sets them on in-order accesses; speculative accesses do not set
  them).
* **SDR1** specifies the variables for accessing the page tables in memory;
  **SDR1[HTABORG]** = base of the hash table, **SDR1[HTABSIZE]** = size.

---

## 3. Implementation in the compiled model

### 3.1 Block map (signal names from the model symbol table)

| Block | Signals | Role |
|-------|---------|------|
| `IT0` | `ITAA.IMIDDLE.IMISC1/2` (`IXICBI`, `ISWRITE`, `IUPDATE_LRU`, `ITAGWRITE`, `IUPDATE_STAT`, `XBIST_READ`), `ITAA.RMW_INDEX`, `ITAA.RMW_LRU0/1`, `ITAA.LATB0..7`, `ITAB.CR`, `ITAC.CR` | **I-TLB tag array** (read-modify-write index, LRU, tag write, `icbi` support) |
| `ICC` | **`ITLB_HIT`/`ITLB_HIT1`** (0x7B91/0x1B72), **`LIBAT_WIMG`** bits 0–3 (0x8A91..0x8D91, 0x2172..0x2472), `WAY_SEL_LAT`, `VALID0..3_L1/L2`, `IM0_VALID0/1`, `IM0_LRU`, `IM0_TBIT/SBIT`, `WORD_INDEX_CNTR` | instruction-side MMU/cache control: I-TLB hit, I-BAT WIMG, I-cache way select / valid / LRU |
| `DMM` | **`L1_TLB_HIT`/`L1_TLB_HIT1`** (0x8840/0x1341), **`LBAT_HIT`** (0x8C40), `LBAT_IG`, `LBAT_G`, `LBAT_WI`, `LBAT_LDI`, `LBAT_DAC_MBIT`, `L1_DM0_LRU`, `L1_DMM_REQ`, `L1_DMM_TLBIE` (`tlbie`!), `DEL_DBAT`, `DEL_SEG`, `DABR_EXCEP` (data-address-breakpoint!) | **data MMU control**: D-TLB hit, D-BAT hit + WIMG, LRU, tlbie, DABR |
| `MM0` | `DMBA..DMBG`, `DMXV/DMXU/DMXR/DMXM/DMXB/DMXC/DMYA`, `BIST_ADDR` | **MMU data arrays** (translation entries / tags) + MMU BIST |
| `DAE` | **`SIZE_WIM`** bits 0–7 (0x002F..0xF72E), `ST_RID`/`LD_RID`, `MISS_CSE`/`SNP_CSE`/`DMA_CSE`/`ADDR_0/1_CSE`/`BIST_CSE`, `STWX_INST`/`LWX_INST`, `WCNT`, `BCNT_CB`, `CBL0/1`, `IN_CB`/`IN_LF`/`IN_SCB`, `LF_L`, `IBIT_HOLD`, `VALID0`, `LD_GRAPH`/`ST_GRAPH` | **data address translation**: access size + WIMG, real-ID, cache-set compare, lwarx/stwcx. tagging |
| `TWC` | **`PTE_MATCH`** (0x1FED/0x63ED), `ITW_OP` (0x24ED), `PF_ITW_START`/`PF_DTW_START`, `PF_ITW_START_D`, `ITW_NO_TEA`/`DTW_NO_TEA`, `NO_ENTRY_D`, `NO_ENTRY_COND`, `TWCB/TWCC/TWCD/TWCJ/TWCK/TWCM/TWCN/TWCR/TWCX/TWCZ/TWCJJ/TWXY/TWCMM`, `BLK_LD_D`/`BLK_LD_DD`, `CHGSTREAM` | **translation-walk controller** — the hardware page-table walker (PTE match, I/D walk start, no-entry conditions) |
| `CSC` | `ACSDR1` (0x3D29), `ACCDAR` (0x4729), `ACCBAT` (0x4829), `IBATS` (0x6D29), `DSISR` (0x5729), `CXER`, `TB_STATE0/1`, `TB_CARRY`, `DEC0/1` | **system-register unit**: SPR access controls for SDR1/DAR/BAT, DSISR, XER, time base/decrementer |

### 3.2 Key slots (for probing with cosim.py / the decompiler)

| Signal | Slots (L1/L2) |
|--------|---------------|
| `DMM.LBAT_HIT` | 0x8C40 / 0x0341 |
| `DMM.L1_TLB_HIT` | 0x8840 / 0x1341 |
| `DMM.LBAT_WI/IG` | 0x8F40,0x9040 / 0x0F41,0x0B41,0x0241 |
| `DMM.L1_DM0_LRU` | 0x8340 / 0x0C41 |
| `ICC.ITLB_HIT` | 0x7B91 / 0x1B72 |
| `ICC.LIBAT_WIMG` | 0x8A91..0x8D91 / 0x2172..0x2472 |
| `TWC.PTE_MATCH` | 0x1FED / 0x63ED |
| `TWC.ITW_OP` | 0x24ED / 0x6FED |
| `TWC.PF_ITW_START` | 0x27ED / 0x66ED |
| `DAE.SIZE_WIM` | 0xD32E..0xF72E / 0x012F..0x392F |
| `DAE.ST_RID` | 0xF32E..0xDC2E / 0x002F..0x3B2F |
| `IT0.ITAA.RMW_INDEX` | 0x7E6D |
| `IT0.ITAA.RMW_LRU0` | 0x7CC4 / 0x7CDC |
| `CSC.ACSDR1/ACCDAR/ACCBAT/DSISR` | 0x3D29/0x4729/0x4829/0x5729 |

---

## 4. Disassembled regions

### 4.1 DMM.LBAT_HIT — data-BAT compare (0x302944)

```
00302924: stw   r25, -0x73c4(r13)
00302928: lwz   r28, 0x7e5c(r13)      ; BAT upper register entry
0030292c: rlwimi r27, r28, 0x18, 8, 0x1f  ; shift/merge BAT fields
00302930: and   r27, r27, r9           ; compare against the EA bits
00302934: lwz   r21, -0x2384(r15)
00302940: or    r12, r12, r27          ; accumulate BAT hit
00302944: stw   r12, -0x73c0(r13)      ; -> BAT-hit / physical address
```
A 32-bit BAT-array compare: the BAT entry is rotated/merged and ANDed with
the effective-address bits; hits from the four BAT pairs are OR-ed.

### 4.2 DMM.L1_TLB_HIT — D-TLB hit (0x23EFB4)

```
0023ef9c: lwz  r26, -0x3974(r14)       ; TLB entry (tag/data)
0023efa4: lbz  r31, 0x7e77(r14)        ; valid bit
0023efa8: cmplwi r31, 0
0023efac: beq  0x23efc0               ; invalid -> miss path
0023efb0: lwz  r22, -0x3950(r14)       ; physical address
0023efb4: stw  r22, -0x77c0(r13)       ; -> translated address out
```
TLB valid-bit check then physical-address output (the D-TLB hit path).

### 4.3 DAE.SIZE_WIM — access size + WIMG merge (0x1A1418)

```
001a13fc: lbz r26, 0x7ff7(r14)         ; WIMG / size source A
001a1404: lbz r8,  -0x7a36(r15)        ; source B
001a1408: or  r28, r8, r26
001a1414: or  r26, r8, r28
001a1418: stb r26, 0x2f(r15)           ; DAE.SIZE_WIM.BIT6
```
The access-size and WIMG fields are OR-combined into `SIZE_WIM` (used by
the cache/MMU to qualify the access).

### 4.4 IT0.ITAA.RMW_INDEX — I-TLB read-modify-write index (0x400CF8)

```
00400cd8: lbz r21, -0x73e2(r14)
00400cdc: and r21, r21, r31
00400ce4: lbz r21, -0x3073(r14)
00400cec: and r21, r21, r31
00400cf0: andc r28, r28, r31
00400cf4: or  r28, r28, r21
00400cf8: stb r28, 0x7e6d(r14)         ; IT0.ITAA.RMW_INDEX
```
Mux of the TLB index sources (EA page index / walker index / BIST) — the
read-modify-write index of the 128-entry I-TLB.

### 4.5 TWC — walker cells (disassembled)

**PTE_MATCH is a read-only (external) input.**  A byte-level search of the
entire model code finds **no store** to slots `0x1FED` (PTE_MATCH.L1) or
`0x63ED` (PTE_MATCH.L2) for any bank — only loads:

```
0x27CC1C  lbz  r8,  0x1FED(r14)   ; PTE_MATCH.L1 — init-region consumer
0x48544C  lbz  r29, 0x63ED(r14)   ; PTE_MATCH.L2 — per-cycle consumer
0x0B98D0  lbz  r8,  0x63ED(r13)   ; bank-0 copy — init-region consumer
```

The compiled netlist writes every internal wire exactly once, so a wire
with no writer is an **input port**: the PTE compare is performed by the
external core/testbench (MVLSIM "ppc" CPU), and the model consumes the
result.  The consumers propagate it into the bus/L2 error-qualification
latches, e.g. the cell at `0x27CC1C` (decompiled):

```
w[1][760E] <= (PTE_MATCH.L1 & ~w[1][75F1]) | (w[2][-6A20] & w[1][75F1]) ...  // GKO.BDT.QUAL_LAT5.L2
w[1][760F] <= (w[1][1FEE] & ~w[1][75F1]) | (w[2][-6A1F] & w[1][75F1]) ...   // GKO.BDT.QUAL_LAT6.L2
```

**Walker state machine (next-state, XOR/toggle cells)** — `0x3DABC0..0x3DACF8`
(decompiled):

```
w[1][6F7C] <= ((w[1][6EBA] ^ r12) ^ w[1][6F5B]) ^ r28;          // GKO.HI1.HIRB.NAN2.L2
w[1][6F5B] <= (GKO.TWC.TWCZ.BIT1.L2 ^ GKO.HI1.HIRB.NAN2.L2);    // parity of state bits
w[1][6CED] <= (w[1][6F5B] ^ w[1][6EC6]) ^ (w[1][6F55] ^ w[1][6F7E])
              ^ GKO.TWC.TWCZ.BIT1.L2;                            // GKO.TWC.TWCZ.BIT1.L2 (toggle)
w[1][716E] <= GKO.HA0.HACA.NAN5.L2 ^ ...;                        // GKO.HIC.HIB0.BIT4.L2
w[1][6E7B] <= (GKO.CDC.FRENV1.BIT3.L1 ^ w[1][6F44]);             // GKO.IC0.ICAB.CR.L1
```

The walker state bits (`TWCZ/TWC*`, `HIRB`, `HIB0`) are updated with
XOR/toggle equations fed by instruction-fetch activity (`GKO.FE0.FEAB`,
`GKO.IC0.ICAB.CR`) — an encoded (counter-like) state machine, not a
priority-decoded one.

**Walk-start / operation cells.**  `TWC.ITW_OP.L2` (`0x6FED`) is written by
enable-gated AND cells, e.g. `0xF4118`:

```
0F410C  nor   r29, r26, r9
0F4110  and   r26, r26, r28
0F4114  and   r26, r26, r24
0F4118  stb   r26, 0x6FED(r14)    ; GKO.TWC.ITW_OP.BIT0.L2 = (op & en1 & en2)
```

The walk-start signals are consumed by per-cycle cones that build the
walker control outputs, e.g. `PF_ITW_START` read at `0x25004C`,
`CSC.ITWSTART` read at `0x262610`, `NO_ENTRY_D` at `0x2674CC`,
`NO_ENTRY_COND` at `0x24CEFC`, `UPDATE_REQ` at `0x2B9574`,
`TW_DONE` at `0x2B4CDC`, `CHGSTREAM` at `0x2486CC`, `ITW_NO_TEA` at
`0x258FEC`, `DTW_NO_TEA` at `0x28F9CC` (all in entry #3).

**Note on L1/L2 copies.**  Many TWC signals exist as an L1 slot and an L2
slot.  The cells write one copy (e.g. `TWCZ.L2` is written 48 times) and
the other copy is a phase copy maintained by the simulator at the cycle
boundary; the interpreter therefore sees the written copy only.

### 4.6 IT0 — I-TLB tag-array cells (disassembled)

**I-TLB hit / LRU cells** — cluster `0x17A9E0..0x17AB58` (init pass) with
per-cycle copies at `0x1BC758..0x1BC954` and `0x1DFB74/0x1DFC44` (entry
#2).  The cells write the hit/latch signals and update the LRU bits from
the way-hit information:

```
17A9E0  stb  r28, 0x7CBC(r14)   ; GKO.IT0.ITAA...IHITLX_X8.HIT_LX.L1
17A9F8  stw  r21, 0x7B30(r14)   ; way/entry select
17A9FC  lbz  r22, 0xE91C(r15)   ; GKO.QSR.TSCC.NAN1.L2  (fetch tag)
17AA04  stb  r22, 0x7CCD(r14)   ; GKO.IT0.ITAA.RMW_LRU1.L1
17AA10  lbz  r24, 0xE920(r15)   ; GKO.GE0.WPCB.NAN1.L2
17AA20  stb  r24, 0x7CD3(r14)   ; RMW latch
17AA2C  stb  r23, 0x7CDE(r14)   ; GKO.CCC.RNBUFF2.BIT2.L2 -> latch
```

The **ITLB_HIT cell** — `0x2A540..0x2A548` (init pass):

```
002A540  or    r11, r11, r21
002A544  nor   r11, r11, r23
002A548  stb   r11, 0x7B91(r14)   ; GKO.ICC.ITLB_HIT.BIT0.L1
```

with inputs from the I-cache latches `0x74AA`, `0x74B7`, `0x749B`,
`0x7497` (L2DCACHEL), `0x74AC` (ICAA.FWD_LAT) — the I-side TLB hit is
derived from the fetch tag compare and the I-cache forward state.

### 4.7 MM0 — MMU data arrays (disassembled)

**SPR register file (BAT/SR/SDR1 storage).**  The `mtspr`/`mfspr` read
path at `0xA3C98..0xA3E60` accesses a register file of **12-byte entries**
(two 32-bit words + one byte) indexed by the select latch `0x7D30`
(`GKO.IT0.ITAA.LATB2`), stride 12, table bases `0x366294`, `0x3668AC`,
`0x36EEC4`, `0x3674DC`:

```
A3C98  addi   r10, r20, -0xB24
A3C9C  addis  r10, r10, 0x2F        ; r10 = 0x3674DC (table A)
A3CA0  cmplwi r25, 0
A3CA4  beq    A3CD0                 ; skip unless an SPR read is valid
A3CA8  lwz    r11, 0x7D30(r14)      ; SPR select latch
A3CAC  mulli  r11, r11, 0xC
A3CB0  add    r11, r11, r10         ; entry = table[select]
A3CB4  lwz    r31, -0x8000(r11)     ; entry word 0
A3CB8  lwz    r9,  -0x7FFC(r11)     ; entry word 1
A3CC0  lbz    r30, -0x7FF8(r11)     ; entry byte 2
...   (repeated for tables B/C/D, same select)
A3D54  stb    r26, 0xB040(r15)      ; DMM.MSR_DR_HOLD.L1 = table C[select].byte
```

The MSR[DR] bit seen by the DMM comes from table C (`0x3668AC`) entry byte
— i.e. the SPR register file holds MSR/BAT/SR/SDR1 values and the DMM
samples `MSR_DR_HOLD` from it.

**MMU array CR latches.**  Cluster `0x4B3EBC..` (entry #3, 1337
instructions) combines LSU address bits (`GKO.LA0.LAAN.PCN2.L1`, `HA0.HAAI`)
with L2/cache state (`L20.L2DCACHEL...`) into the MM0 array CR latches
(`GKO.MM0.MAAB.NAN6.CR.L2` = `0x6CE7`, `0x6CE8` = `HA0.HACA.NAN3.L2`):

```
4B3EBC  stb  r31, 0x6CE7(r14)   ; GKO.MM0.MAAB.NAN6.CR.L2
4B3EE8  lbz  r11, 0x6C91(r14)   ; GKO.LA0.LAAN.PCN2.L1
4B3EF4  lbz  r8,  0x6C9F(r14)
4B3EFC  andc r11, r29, r8
4B3F1C  stb  r31, 0x6CE8(r14)   ; GKO.HA0.HACA.NAN3.L2
```

The MM0 array data ports (`DMBA..DMX*`, `MAAB`, `BIST_ADDR`) are written
through computed pointers (array-indexed stores, e.g. the `r11 = base +
index*12` pattern above), which is why they have no literal-displacement
writers.

---

## 5. Per-cycle execution model (three entries, two calls per cycle)

The model header declares three bootstrap entries; the real per-cycle flow
uses two of them:

| Entry | Address | Role |
|-------|---------|------|
| #1 (init) | `0x2C` | one-time reset/initialization; evaluates the initial state (405–412k instructions) |
| #2 (per-cycle) | `0x1BCD60` | fast idle path: copies the runtime descriptors into slots `0x4C..0x194`, sets up the bank pointers `r13..r20`, evaluates the idle cells and **returns early at `0x1DE3A4`** unless the simulator's activity flag (call block +0x48, slot `0x8048`) is set; if set, runs the assert/report tail and returns at `0x2341C8` |
| #3 (per-cycle) | `0x2341CC` | the **full netlist** evaluation: all combinational cones with per-condition slice selection (asserts, MMU/BAT/TLB/walker cells), up to the final return `mtlr r10; blr` at `0x4BA83C` |

Measured with the interpreter (`cosim.py`): init = 412,209 steps; idle
entry #2 = 15,261 steps (early return at `0x1DE3A4`); entry #2 with the
activity flag = 54,479 steps (return at `0x2341C8`); entry #3 = 155,133
steps (idle path through the full netlist).

The early-return gates:
* `0x1DE38C..0x1DE3A8`: `lwz r11, 0x8048(r13); cmplwi r11, 0; bne → 0x1DE3AC`
  — with slot `0x8048` (call block +0x48) == 0 the model returns at
  `0x1DE3A4` (idle); with it set, execution continues into the
  assert/report tail and then to entry #3.
* Entry #3 is a decision tree: e.g. the DMM BAT-compare region
  `0x3028E0..0x302974` is skipped by `beq @0x302870` when
  `0xD7D0 | 0xD7D1` (bank 2) == 0, and the following block by `beq
  @0x3029B4` when `0xA712 | 0x7F57` == 0.

### 5.1 Branch semantics (bc) used by the model

The model emits only two conditional-branch encodings (18,913 total):

* `bc 12, BI` — **beq**: branch if `CR[BI] == 1` (9,647 occurrences),
* `bc 4, BI` — **bne**: branch if `CR[BI] == 0` (9,266 occurrences).

(No CTR branches are used.)  An early version of the interpreter treated
`BO=4` as "branch if `CR[BI] == 1`", which inverted every `bne`; this was
fixed in `cosim.py` (the polarity is bit 3 of the BO field).

---

## 6. Live-cycle MMU/BAT probing (`mmu_bat_test.py`)

The DMM BAT-compare cell (store to `DMM.LBAT_HIT` at `0x302944`) is gated
by slot `0xD7D0 | 0xD7D1` (bank 2) ≠ 0 and reads the DBAT register words
(bank-0 slots `0x7E57/0x7E5C/0x7E5F/0x7E63`), LAS access/EA slots
(`0xDC7C`, `0xDC84` = `LAS.LMMS.BIT3.L1`, …) and `MSR_DR_HOLD`
(`0xB040`, bank 2).  `mmu_bat_test.py` injects that state plus the
activity flag (slot `0x8048`) and runs entry #2 + entry #3:

```
init: done (412209 steps)
before eval: LBAT_HIT=0 L1_BAT_HIT=0 BATMISS=0 ...
stage3 (0x2341CC): done (156803 steps)
after stage3: LBAT_HIT=1 L1_BAT_HIT=0 BATMISS=0 ...
```

Results:
* **`DMM.LBAT_HIT` asserts 0 → 1 in a live cycle** (entry #3) when the
  access-present gate and the DBAT words are injected.
* **Control run** (DBAT words and MSR set, but gate `0xD7D0` cleared):
  `LBAT_HIT` stays 0 — the cell is genuinely gated.
* The hit is **latched**: subsequent cycles keep `LBAT_HIT = 1`.
* The full-netlist run with partially injected state also reports three
  real model asserts (CBB SEL1/SEL0, CDC dispatch checks) — expected side
  effects of a partial (non-consistent) machine state.
* The WGB/BNE test (`wgb_bne_test.py`) was re-run with the corrected
  branch semantics and the two-call per-cycle flow: the WGB byte counter
  and `BNE` stay frozen for 120 idle cycles — the no-WGB-timeout
  conclusion is unchanged.

The interpreter (`cosim.py`) was updated accordingly: `ENTRY_STAGE3` is
now called after the main entry in every simulated cycle, and the
`bc` BO=4 semantics were fixed (see §5.1).

---

## 7. Conclusions

1. The Gekko MMU is a **parallel IMMU/DMMU** with **128-entry 2-way LRU
   TLBs**, **4+4 BAT pairs**, 16 segment registers, **SDR1** page tables and
   a **hardware page-table walker**.
2. In the compiled model the MMU is implemented as: the I-TLB tag array
   (`IT0`), the I-side control (`ICC`: `ITLB_HIT`, `LIBAT_WIMG`), the
   data-MMU control (`DMM`: `L1_TLB_HIT`, `LBAT_HIT`, WIMG, `tlbie`,
   `DABR_EXCEP`), the data arrays (`MM0`), the effective→real translation
   (`DAE`: `SIZE_WIM`, `RID`, `CSE`), the **walk controller** (`TWC`:
   `PTE_MATCH`, `ITW/DTW` start, no-entry conditions), and the SPR/exception
   block (`CSC`: `SDR1/DAR/DSISR` access).
3. The disassembled cells show: 32-bit BAT compares (DMM), TLB valid-bit
   hit paths (DMM), WIMG/size merging (DAE), the I-TLB index mux (IT0),
   the I-TLB hit/LRU cells (IT0/ICC), the XOR/toggle next-state cells of
   the walk controller (TWC), and the SPR register file with 12-byte
   entries (BAT/SR/SDR1/MSR storage, indexed by latch `0x7D30`).
4. Probing the MMU state via `cosim.py` (slots listed in §3.2) allows
   observing TLB/BAT hits, WIMG attributes and walker activity during
   simulation.
5. **`TWC.PTE_MATCH` is an external input** — no model cell writes it; the
   PTE compare runs outside the compiled model (MVLSIM "ppc"-type core /
   testbench).  The walk state machine (`TWCZ/TWC*`) is internal.
6. **A live per-cycle D-BAT hit is reproducible**: injecting the
   access-present gate (`0xD7D0|0xD7D1`) + DBAT words + `MSR_DR_HOLD` and
   running entry #3 asserts `DMM.LBAT_HIT` (0→1); the control run stays 0
   (`mmu_bat_test.py`).
7. **The per-cycle flow is a two-call sequence** (`0x1BCD60` then
   `0x2341CC`); the idle fast path returns at `0x1DE3A4` unless the
   simulator activity flag (slot `0x8048`) is set.  `cosim.py` now
   reproduces this and also fixes the `bc` BO=4 (`bne`) polarity.

---

## Appendix A. Reference — manual excerpts (Chapter 5)

* **§5.1** translation flow: real mode (`MSR[IR]`/`MSR[DR]` = 0) → BAT
  compare → segment descriptor (EA[0:3] selects one of 16 SRs; Gekko does
  not implement the direct-store interface — T=1 segments fault) → page
  table search.
* **§5.3 BAT**: "The block address translation (BAT) mechanism provides a
  way to map ranges of effective addresses larger than a single page into
  contiguous areas of physical memory… Gekko's BAT registers are not
  initialized by the hardware reset." 4 IBAT + 4 DBAT pairs, 32-bit SPRs.
* **§5.4.3 TLB**: "Gekko implements separate 128-entry data and instruction
  TLBs to maximize performance… the hardware implementation of the MMU is
  not specified by the architecture… Because Gekko has two MMUs (IMMU and
  DMMU) that operate in parallel, some of the MMU resources are shared, and
  some are duplicated (shadowed) in each MMU."
* **SDR1**: "specifies the variables used in accessing the page tables in
  memory."
* Translation exceptions: Table 5-3 (page fault / block protection / page
  protection / no-execute / direct-store → ISI or DSI with the SRR1/DSISR
  bits shown in §2.1).
