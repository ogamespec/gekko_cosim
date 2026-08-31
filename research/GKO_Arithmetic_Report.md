# Gekko Adders and Multipliers — Research Report

**Subject:** inventory and disassembly of the arithmetic units (adders and
multipliers) of the Gekko microprocessor (GameCube CPU, MPC750-class core).
**Sources:** IBM Gekko RISC Microprocessor User Manual (Version 1.2, 5/25/00),
the compiled logic model `model/COSIM.m2630opt.Jul1599` (MVLSIM), the
decompiler `decompile_model.py` and the disassembler (capstone).
**Document version:** 1.0

---

## 1. Executive summary

1. The Gekko contains the following adders / arithmetic datapaths:
   * **Two integer units** — IU1 (`GKO.XEA`) and IU2 (`GKO.XEB`) — with the
     integer ALU adder (`XEA.ADDER_*`), a comparator, and **multi-cycle
     multiply and divide** units (`mullw/mulli`, `divw/divwu` — the manual:
     "several integer instructions, such as multiply and divide, require
     multiple cycles in the execute stage").
   * **The LSU effective-address adder** — "a dedicated adder performs EA
     calculations" (`GKO.LA0.LAAN` = Load-Address Adder Network, plus the
     `LAS.LAC*` load-address-calc control).
   * **The FPU** — pipeline "Multiply → Add → Normalize → Round"; the adder
     datapath is `GKO.FA0` (arrays `FAAA..FAAJ`, `FACA`), the multiplier is
     the (unnamed) Multiply stage fed by the operand registers `FI0/FI1`
     (`FIRA/FIRB/FIRC` = frA/frB/frC), results written back via
     `FWN/FW0`.
   * **The BPU branch-target adder** — "the BPU contains an adder to
     compute branch target addresses" (unnamed cells in the
     fetch/branch blocks `FIC`/`CBB`).
   * **Counter incrementers** — time base + decrementer (`CSC`: `TB_CARRY`,
     `DEC0`), DMA queue counters (`DM0`/`DMC`), instruction-queue word-index
     counter (`ICC`), store-pipe shift register (`DQ0`).
2. In the compiled netlist the adders are not named per bit: they are built
   from the standard cell pattern
   `Q <= (A & ~S) | (B & S)` / `Q <= ((X & Y) | (X & ~Z) | ...) & en`
   (mux/latch cones). The disassembled regions below show this structure.
3. `GKO.LLC.LAC_MULTS*` / `LLC.MULTS*` are **"multiple stores"** of the
   D-cache write path, *not* a hardware multiplier. The paired-single
   quantization scale (F = I × 2^(−S)) is an **exponent add/subtract +
   shift**, not a multiply array.

---

## 2. Architectural inventory

### 2.1 Integer units — IU1 (XEA) / IU2 (XEB)

From the block diagram (manual page 1-3): "Integer Unit 1", "Integer Unit
2" each with a 2-entry reservation station. In the model:

| Signals | Role |
|---------|------|
| `XEA.ADDER_L2FRZ` (slots 0xC0F1/0xC5F1) | integer **adder** freeze/control |
| `XEA.XEFA..XEFH`, `XEB.XEFA2..XEFH2` | ALU result/datapath slices |
| `XEA.XEAA..XEAD`, `XEB.XEBA..XEBD` | datapath operand slices |
| `XEA.XEZA..XEZF`, `XEB.XEZA2..XEZF2` | zero-detect |
| `XEA.EIB_SM`, `XEB.EIB_SM2` | execution input bus select (operand mux) |
| `XEA.XECA/XECB/XECC`, `XEB.XECA2` | compare / CR result path |
| `XE2` (`XE2C`, `XE2F`), `XF0` (`XFTC`, `XFZB`) | additional integer-slice control |

The multiply (`mullw`, `mulli`) and divide (`divw`, `divwu`) are executed
in the IUs over multiple cycles (the manual's pipeline figure shows
"Execute" as a multi-cycle stage for these); their datapath is inside the
XEA/XEB cells and has no distinct signal names (the model is a compiled
netlist — the Booth/partial-product logic is synthesized into unnamed
cones).

### 2.2 LSU — effective-address adder (LA0.LAAN)

Manual (page 1-5): "Two-stage LSU … **Dedicated adder performs EA
calculations**".

| Signals | Role |
|---------|------|
| `LA0.LAAN.PAN/PBN/PCN/PDN/PEN` (5 operand groups, 63 signals) | the EA adder network (operand and partial-sum/carry groups) |
| `LA0.LAAX/LAAI/LAAJ/LABC/LABP/LABX/LABY/LAXX/LAXY` | EA adder operand/result latches |
| `LAS.LAC*` (LACA..LACZ, LACT, LACP, LACS, LADC 17-bit, LADA/LADB) | load-address calculation control + L1-D-cache address |
| `LAS.LSC_SRC_LFS/LXS`, `LXAA..LXJA` | operand-source muxing into the adder |

Disassembled operand-mux cells: 0x1BB9E0–0x1BBB9C (four mux stages
selecting operand sources into the 0x76xx input slots), 0x1BBDF0 (bit mux
`w[1][7d91] (LAAN.PAN7) <= ((srcA & ~sel) | (srcB & sel)) & en`).

### 2.3 FPU — adder (FA0), multiplier, normalize/round

Manual (page 1-4): "32-Bit Floating-Point Unit … Two-entry reservation
station"; pipeline (page 6-7): **"Normalize / Multiply / Add / Round"**.

| Signals | Role |
|---------|------|
| `FI0.FIRA/FIRB/FIRC`, `FI1.FIRA/FIRB/FIRC` (≈20-bit slices) | FPU operand registers (frA/frB/frC) — the 2-entry reservation station |
| `FDC.FIRA/FIRB/FIRC` (6-bit), `FDDA` (24-bit), `FDCD` | FPU decode/control + operand data |
| `FE0.FEWA/FEWB/FEWE/FEXA/FEAB/FEAF` | FPU execute (write enables, execute control) |
| `FA0.FAAA..FAAJ`, `FA0.FACA` (11 arrays of ~13 bits; slots 0x5758–0x5C98) | **FPU adder** datapath (mantissa/exponent add) |
| `FWN` (`FWN0..9`, `FWSV..FWSZ` 16-bit buses), `FW0` (`FWAA..FWAD`), `FWC` | FPU write-back network → FPR file |
| `FW2`/`HW2` (`FW2Z`, `FWTC`) | second write-back/control slices |

The **multiplier** is the "Multiply" pipeline stage between the operand
registers (FI0/FI1) and the adder/normalize stage; in the netlist it is
implemented as unnamed logic cones (no `MUL`/`BOOTH` signal names exist in
the model — the only "MULTS" name, in LLC, means multiple stores, see
§2.6).

Disassembled: the FA0 operand/result registers are loaded as 32-bit words
from the FPU data path, e.g. 0x2F4810–0x2F482C
(`lwz rX, disp(r15); stw rX, 0x5A28/0x5A24/0x5A20/0x5A1C(r13)` →
`FA0.FAAA.NAN*`).

### 2.4 BPU — branch-target adder

Manual (page 1-8): "The BPU contains an adder to compute branch target
addresses and three user-control registers — the LR, the CTR, and the CR."
In the model the branch unit logic lives in the fetch/BHT blocks
(`FIC`, `CBB`); the target adder cells are unnamed (no `TARG`/`BTAR`
signals are present in the symbol table).

### 2.5 Counters / incrementers (adders with a "+1" input)

| Unit | Signals | Counter |
|------|---------|---------|
| `CSC` | `TB_STATE0/1` (0x0329/0x0429), `TB_CARRY` (0x0529), `DEC0` (0x0729) | 64-bit **time base** + **decrementer** (increment/decrement adders with carry) |
| `DM0`/`DMC` | `DMA_Q0_CNT_LD`, `DMA_Q*_CNT`, `DMA_Q_STATE`, `DMC_QCNT0..3`, `DMAQOV` | DMA command-queue counters |
| `ICC` | `WORD_INDEX_CNTR` | instruction-cache word-index counter |
| `DQ0` | `ST_PIPE_SHIFT_REG` | store-pipe shift register |
| `JTC` | `RUNNCOUNTER1`, `DIAGLAT*` | JTAG/diagnostic counters |
| `GE0` | `QNTR0..7` | queue/status counters |

### 2.6 Non-multipliers

* `GKO.LLC.LAC_MULTS_GPR_M/H`, `LLC.MULTS`, `LLC.BLK_MULTS`,
  `LLC.BLK_FINISH_MULTS`, `LLC.MULTS_WE_STATE` — **MULTiple STorES** of the
  L1 D-cache write path (the `_M`/`_H` are the two 32-bit lanes), *not* a
  hardware multiplier.
* Paired-single quantization scale (F = I × 2^(−S)) is an **exponent
  add/subtract** (GQR LD_SCALE/ST_SCALE) with mantissa shift — no multiply
  array (see the paired-single report).

---

## 3. How the compiled cells implement an adder

The model is a flat PowerPC program whose instructions are the netlist
cells. An adder bit is a logic cone of loads + boolean ops + a store. The
recurring building blocks observed in the disassembly:

* **Mux (operand select)**: `w[dst] <= (A & ~S) | (B & S) & en`
  (e.g. `LA0.LAAN.PAN7` at 0x1BBDF0; the LAAN operand muxes at
  0x1BB9E0–0x1BBB9C which `lbz` a group of sources and `stb` them into the
  adder input slots 0x75EE–0x76B8).
* **Carry/sum cones**: sequences of `and`/`andc`/`or`/`nor`/`xor` over
  loaded operand bits producing the sum and the propagate/generate terms
  (the carry chain connects adjacent bit cells via the carry slots).
* **Register loads**: 32-bit operand/result words are loaded with
  `lwz`/`stw` pairs (e.g. the FA0 adder registers at 0x2F47xx).

Because the synthesis tool did not preserve gate names, only the *anchors*
(`LA0.LAAN`, `XEA.ADDER_*`, `FA0.*`, `CSC.TB_CARRY`) are named; the
full-adder arrays themselves are unnamed slots.

---

## 4. Disassembled regions (representative)

### 4.1 LA0.LAAN — EA adder operand muxes (0x1BB9E0..0x1BBB9C)

```
001bb9e0: stb r28, 0x7691(r14)      ; -> adder input slots (0x76xx)
001bb9f0: lbz r12, -0x4ca5(r15)     ; source A
001bb9f8: lbz r24, -0x4c8d(r15)     ; source B
001bba04: stb r23, 0x76b7(r14)
001bba14: b   0x1bbbbc              ; select branch (mux)
001bba18: lbz r28, 0x7279(r14)      ; alternative source group
... (three more mux stages, each lbz-ing a source group and stb-ing
     into 0x75EE..0x76B8 = the EA adder operand latches)
```

### 4.2 LA0.LAAN — bit mux (0x1BBDF0)

```
001bbde4: or   r31, r31, r22
001bbde8: lbz  r8, -0x1940(r15)
001bbdec: and  r31, r31, r23         ; enable
001bbdf0: stb  r31, 0x7d91(r14)      ; LAAN.PAN7 <= ((A & ~S) | (B & S)) & en
```

### 4.3 FA0 — FPU adder operand registers (0x2F480C..0x2F482C)

```
002f480c: lwz r27, -0x36b8(r15)      ; FPU data path
002f4810: lwz r26, -0x2ea4(r15)
002f4814: stw r26, 0x5a28(r13)       ; FA0.FAAA.NAN* (L2)
002f4820: stw r12, 0x5a20(r13)
002f4828: stw r29, 0x5a18(r13)       ; FA0.FAAA.NAN4
```
The FA0 adder inputs/results are 32-bit words moved between the FPU
datapath and the adder arrays.

### 4.4 XEA — integer adder control (0xC0F1)

```
GKO.XEA.ADDER_L2FRZ.BIT0.L1/L2  (slots 0xC0F1 / 0xC5F1)
```
The adder freeze/enable for IU1; the sum/carry cones are the unnamed
`XEAA..XEAD`/`XEFA..XEFH` datapath cells.

### 4.5 CSC — time base / decrementer counters

`TB_STATE0/1`, `TB_CARRY`, `DEC0` (slots 0x0329..0x0729, L2 at 0xF028..0xF928):
the 64-bit time-base counter (upper/lower halves + carry) and the
decrementer are the increment/decrement adders of the system timer unit.

---

## 5. Conclusions

1. The Gekko's arithmetic hardware is organized as: two integer ALUs
   (XEA/XEB, incl. multi-cycle multiply/divide), the dedicated LSU EA adder
   (LA0.LAAN + LAS.LAC), the FPU (operand regs FI0/FI1 → **Multiply** →
   **Add** (FA0) → normalize → round → FWN/FW0 write-back), the BPU
   branch-target adder, and several counter incrementers (time base,
   decrementer, DMA, ICC, store pipe).
2. In the compiled model the adder/multiplier *arrays* are unnamed logic
   cones; the named anchors are `LA0.LAAN`, `XEA.ADDER_*`, `FA0.*`,
   `CSC.TB_CARRY`. The build cells are mux/latch cones of the form
   `Q <= (A & ~S) | (B & S)` and 32-bit word moves.
3. `LLC.MULTS*`/`LAC_MULTS*` = multiple stores (D-cache write), not a
   multiplier; the PS quantization scale is an exponent add/sub, not a
   multiply.

---

## Appendix A. Reference material

* Manual: sections 1.2.1 (block diagram, "dedicated adder performs EA
  calculations"), 1.2.2.2 (BPU adder), 6.4 (execution timing; "several
  integer instructions, such as multiply and divide instructions, require
  multiple cycles in the execute stage"), 6.7 (instruction latency
  summary), Chapter 12 (divw/mullw descriptions).
* Model files: `model/COSIM.m2630opt.Jul1599.names.txt` (signal names),
  `model/WGB_logic_decompile.txt`, decompiler `decompile_model.py`,
  interpreter `cosim.py`.
* Disassembly regions cited: 0x1BB9E0–0x1BBB9C (LAAN muxes),
  0x1BBDF0 (LAAN bit), 0x2F47xx (FA0 registers), 0xC0F1 (XEA.ADDER),
  CSC slots 0x0329–0xF928 (time base/decrementer).
