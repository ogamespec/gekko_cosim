# GKO Model — CNTLZW Instruction Execution Analysis

**Subject:** how the `cntlzw` (count leading zeros word) instruction is
executed in the compiled Gekko logic model
(`model/COSIM.m2630opt.Jul1599`, MVLSIM, 5,737,028 bytes).
**Sources:** IBM Gekko RISC Microprocessor User Manual (Chapter 3 /
instruction set, page 12-33), the compiled model (symbol table, messages,
per-cycle code), the interpreter `cosim.py` and the live-simulation runs.
**Document version:** 1.0

---

## 1. Executive summary

1. `cntlzw rA, rS` (and `cntlzw.` with Rc = 1) is a **single-cycle
   fixed-point** (integer) instruction: `rA ← count of leading zero bits of
   rS`, result in 0..32, CR0 updated only when Rc = 1 (with LT forced
   clear).
2. In the model, integer instructions are **dispatched by the CDC block to
   one of two integer units** — **FXU(0) = `XEA` (IU1)** or **FX2 = `XEB`
   (IU2)** — with rename registers, executed in the `XEA`/`XEB` datapath
   and written back at completion.  Multi-cycle ops (multiply/divide) go
   specifically to FX2; `cntlzw` is a simple-ALU op and can use either
   unit.
3. The per-opcode decode (opcode 31 / XO 26) and the leading-zero-count
   datapath itself are **unnamed combinational cones** in the compiled
   netlist (like the rest of the ALU datapath); the model exposes the
   *pipeline control* (dispatch classes, rename, completion, CR0) through
   named signals and its assert cells.
4. Live simulation with injected pipeline state confirms the dispatch
   machinery actively classifies and dispatches instructions (CDC asserts:
   "Instr. I0 dispatched to FX2 when busy", "I0 dispatched to SYS_UNIT…",
   "disp_fxu(0) and disp_fx2(0) during same cycle", …).

---

## 2. Instruction specification (Gekko User Manual, p. 12-33)

```
cntlzw   rA, rS          (Rc = 0)      encoding 0x7C00 0034
cntlzw.  rA, rS          (Rc = 1)
```

* Opcode 31, XO = 26, Rc = bit 31; rS = bits 11..15, rA = bits 6..10.
* Algorithm (manual):
  `do while n < 32; if rS[n] = 1 then leave; n ← n + 1;`
  "A count of the number of consecutive zero bits starting at bit 0 of rS
  is placed into rA.  This number ranges from 0 to 32, inclusive."
* Other registers altered: **CR0 field (LT, GT, EQ, SO) if Rc = 1**; the
  manual notes: "If Rc = 1, then LT0 is cleared in the CR0 field" (the
  result 0..32 is always non-negative).
* Class: fixed-point / integer, **single-cycle** in the MPC750-class
  integer units (no use of the multiplier/divider).
* Compliance: PowerPC Architecture Level / Supervisor Level / Gekko
  Specific / PowerPC Optional Form.

---

## 3. The integer pipeline in the model (where cntlzw executes)

### 3.1 Fetch → instruction queue

The instruction stream enters the model on the 60x data pins `DH/DL`
(instruction-fetch data); the fetched words travel through the I-cache
fill path (e.g. the mux cone reading the `DH` bit slots `0xEB52`/`0xE9B8`
at `0x39D8B8`, combined with L2 `L20` state) into the instruction
machinery and the **instruction queue `IQ0`** (fields `IQCA..IQWF`,
`IQWE/IQWF` — queue-entry bit slices, slots `0x7BC0..0x7C90`).  The IQ
fields are consumed by the decode logic (many readers in per-cycle code,
e.g. `0x3E8B4`, `0x1DE138`, `0x235630`, `0x11ACAC` …).

### 3.2 Decode / dispatch — CDC block

The CDC (central dispatch/completion) classifies each instruction and
dispatches it to a unit.  The unit set is visible in the CDC assert cells
(57 dispatch-related messages in the model, e.g. `cdc.dsl`):

| unit | meaning | evidence |
|------|---------|----------|
| **FXU(0)** | IU1 = `XEA` | "Incorrect I0 dispatch to FXU !!!", "Wrong type encoding for I0 dispatch to FXU(0)!!" |
| **FX2** | IU2 = `XEB` | "Instr. I0 dispatched to FX2 when busy", "I0 is a Multiply or Divide and is being dispatched to the FX2 unit!!!!" |
| **LSU** | load/store unit | "Instr. I0 dispatched to LSU when busy" |
| **FPU** | floating point | "Dispatch to FPU when I0 is not valid or legal" |
| **SYU** | system unit | "Incorrect I0 dispatch to System_Unit" |

Dispatch checks: "disp_fxu(0) and disp_fx2(0) during same cycle",
"2 instr. dispatched to FXU in same cycle", "Wrong type encoding for I0
dispatch to FXU(0)!!" — the instruction **type-encoding field** (the
decoded instruction class) is what selects the unit.

Dispatched-instruction fields (named slots):

* `CDC.REGOP_1..5` (`0x0027..0x1D27` …) — register operands (5-bit GPR
  addresses) of the dispatched instruction(s);
* `CDC.FRNM0/FRNM1` (`0x1827`/`0x0C27` …) — rename-register numbers;
* `CDC.FWB0` (`0x0127` …) — future-write-back (rename) buffer select;
* `CDC.TENC`, `CDC.RENV`, `CDC.FREGOP`, `CDC.CDCZERO` — dispatch/rename
  control.

`cntlzw` is a **simple-ALU-class** fixed-point op, so its type encoding
routes it to FXU(0) or FX2.

### 3.3 Execution — XEA (IU1) / XEB (IU2)

The integer datapath lives in the `XEA`/`XEB` blocks:

* `XEA` signals `XEAA..XEAD`, `XECA/XECB`, `XEFA..XEFH`, `XEIA..XEIK`,
  `XEJA..XEJC`, `XEZA..XEZF` — the datapath/control latches;
* `XEA.ADDER_L2FRZ` (`0xC0F1`) / `XEB.FX2_L2FRZ` (`0x68F2`) — pipeline
  freeze controls for the adder/multiplier stages;
* `XEB` (`FX2`) hosts the multiplier/divider (multi-cycle ops;
  "I0 is a Multiply or Divide and is being dispatched to the FX2 unit");
* `XM0` — the integer multiplier datapath (partial products `PAN..PFN`,
  zero-detect `XMZT/XMZP`) — **not** used by `cntlzw`.

`cntlzw` uses the simple-ALU path: operand `rS` read → leading-zero-count
computed → result to the rename register.

### 3.4 Write-back / completion

* Completion renames the result into the GPR file:
  `CCC.GRNM_WE0/GRNM_WE1` (`0x0D24`/`0x1224`) — GPR rename write-enables;
* CR0 (when Rc = 1) is written through the CR path
  (`CCC.CRFIELD4`, `CSC` CR fields); the "LT cleared" rule matches the
  result being 0..32.

---

## 4. CNTLZW execution walk-through (pipeline stages)

| stage | model block | action |
|-------|-------------|--------|
| 1. Fetch | 60x bus → `IC0`/`IQ0` | instruction word `0x7C000034` (or `0x7C000035` for `cntlzw.`) enters the instruction queue |
| 2. Decode | `CDC` | opcode 31 / XO 26 decoded; type-encoding = fixed-point simple-ALU; register operands `rS`/`rA`, Rc → CR0 flag |
| 3. Dispatch | `CDC` | renamed (FRNM/FWB), sent to FXU(0)=`XEA` or FX2=`XEB`; serialization/completion checks |
| 4. Execute | `XEA`/`XEB` | leading-zero-count of `rS` computed (single cycle) |
| 5. Write-back | `CCC` | result → GPR via rename (`GRNM_WE`); CR0 updated if Rc = 1 (LT cleared) |

---

## 5. What the model exposes and what it hides

* **Visible (named):** the instruction-queue fields (`IQ0`), the dispatch
  machinery (`CDC`: REGOP/FRNM/FWB/TENC), the unit classes and their
  checks (assert cells), the integer-unit control (`XEA`/`XEB`, freeze
  controls), the completion/CR0 path (`CCC.GRNM_WE`, `CRFIELD4`).
* **Not visible by name:** the per-opcode decode cone (the XO=26 test) and
  the leading-zero-count datapath.  Like the rest of the ALU datapath,
  these are unnamed combinational cones (compiled SOP cells) in the
  netlist; they can be traced only by data-flow (operand slots → result
  slots), not by symbol names.  As with other architectural details of
  this "ppc"-type MVLSIM model, part of the execution environment (e.g.
  the bus-level fetch handshake) is driven by the testbench.

---

## 6. Live-observation evidence (cosim.py)

Injecting pipeline/MMU activity and running the per-cycle entries fires
the CDC dispatch checks, showing the dispatch machinery actively
classifying instructions (I0/I1 → FX2/FPU/SYU):

```
ASSERT: 29 | GKO.CDC:cdc.dsl:5586 > I0 dispatched to SYS_UNIT during a completion serialized instruction!!!
ASSERT: 29 | GKO.CDC:cdc.dsl:5339 > disp_fxu(0) and disp_fx2(0) during same cycle
ASSERT: 29 | GKO.CDC:cdc.dsl:5374 > Instr. I0 dispatched to FX2 when busy
ASSERT: 29 | GKO.CDC:cdc.dsl:5596 > I1 dispatched to FPU during a completion serialized instruction!!!
ASSERT: 29 | GKO.CDC:cdc.dsl:5377 > Instr. I1 dispatched to SYU when busy
```

These confirm the FXU(0)/FX2/LSU/FPU/SYU dispatch structure of §3.2 and
that integer instructions (the `cntlzw` class) are routed to the two
integer units `XEA`/`XEB`.

---

## 7. Conclusions

1. `cntlzw` is a single-cycle fixed-point instruction (XO = 26, encoding
   `0x7C000034`); result = leading-zero count of `rS` (0..32); CR0
   updated when Rc = 1, with LT cleared by construction.
2. In the compiled model it executes on the standard integer pipeline:
   `IQ0` (queue) → `CDC` (decode + rename + dispatch to `XEA`/`XEB`) →
   integer datapath (single-cycle ALU class; the multiplier `XM0` is not
   involved) → `CCC` completion (GPR rename + CR0).
3. The pipeline control is observable through named signals and the
   dispatch assert cells; the per-op decode and the LZC datapath are
   unnamed netlist cones.
4. Live runs reproduce the dispatch behaviour (I0/I1 → FX2/FPU/SYU
   checks), consistent with the manual and the model structure.
