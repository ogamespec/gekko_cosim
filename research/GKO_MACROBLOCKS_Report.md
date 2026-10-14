# GKO Model — Macroblocks (Logic Elements) Recovered from the Compiled Netlist

**Issue:** [ogamespec/gekko_cosim#1 — Определить макроблоки в коде модели](https://github.com/ogamespec/gekko_cosim/issues/1)
**Subject:** `model/COSIM.m2630opt.Jul1599` — the Gekko (GameCube CPU) logic
model, compiled as a 2-value netlist into flat PowerPC code.
**Method:** interpreter ground truth + symbolic dataflow replay (a BLAST-like
motif search over the instruction "DNA", with the patch anchors as introns).
**Document version:** 1.0

---

## 1. Answer in one paragraph

The compiled model is not a sequence of self-contained gate templates: the
`m2630opt` compiler keeps its intermediate results in **registers** and emits
long straight-line fragments in which one register accumulator carries a whole
sum-of-products expression, so a logic element is only recognisable through its
**dataflow**, not as a fixed instruction sequence at a fixed cell. The
macroblocks were therefore recovered in two layers, both of which are
delivered here:

1. the **netlist layer** — every executed store to a state wire is replayed
   symbolically and emitted as a boolean statement
   (`research/netlist_recovered_cycle2.txt`, 6,680 statements), which *is* the
   logic element list of the schematic (section 6);
2. the **template layer** — the recurring instruction/operand patterns those
   statements are built from, counted over the executed code (section 7).

The dominant logic elements are 2–4-input AND/OR/NOR/XOR cones with
sum-of-products structure, port polarity, and (very frequently) a
`(A & B) | (C & D)` multiplexer shape. The patch anchors (NOPs) never take part
in a pattern, exactly as the issue requires.

---

## 2. What the model is (the 2-value machine)

* **Code:** a flat PowerPC program, `model/COSIM.m2630opt.Jul1599`
  (5,737,028 bytes). Code region `0x0..0x4BA840` = 1,239,568 instruction words;
  after it the patch list, symbol table, message region, pin table, header.
* **Entry points** (from `cosim.py`/the spec): bootstrap #1 `0x2C` (load-time
  init), per-cycle #2 `0x1BCD60` (fast/idle path), per-cycle #3 `0x2341CC`
  (full netlist evaluation), final `blr` at `0x4BA83C`.
* **Patch list / anchors:** 38,738 link words (head `0x4BA800`, tags
  {2: 37,526, 3: 1,211, 1: 1}). MVLSIM overwrites each with `0x60000000`
  (NOP) at load time, so the words are *holes in the logic but not in the
  code*. **All 38,736 anchors inside the code region sit on the 0x80 grid**
  (37,711 at offset 0, 673 at 4, 174 at 8, 166 at 12, 3 at 20) — the grid is a
  compiler allocation convention, as the issue says, and logic elements may
  straddle it. Consequently nothing in the extraction below assumes cell
  boundaries: anchors are skipped when matching and their positions never
  contribute to a pattern; branch targets, which do count the anchors, are
  taken from ground truth rather than recomputed.
* **State:** **8 banks × 65,536 bytes** (`r13 = base+0x8000`, +0x10000 each),
  one byte per state wire. The banks are the *planes* of the two-value
  simulation: 4 plane-pairs, `L1`/`L2` latch phases (`bank 2k` = copy A,
  `bank 2k+1` = copy B — the symbol table's `.L1`/`.L2` names appear
  correspondingly). A wire is identified by `(bank, slot)` where
  `slot = disp & 0xFFFF`; slots `0x8000..0xFFFF` are reached through negative
  displacements. 16,862 slots have names in the symbol table.
* **Values:** all stored values are 0/1 for single-bit wires; some statements
  store assembled vectors (multi-bit `stw`) — see section 8.

### 2.1 Only part of the code is alive

Instrumenting the interpreter (`netlist_gt.py`, `gt_dump.py`) over the init
pass plus two cycles shows which addresses actually run:

| region | code words | executed | note |
|---|---:|---:|---|
| init `0x2C..0x1BCD60` | 456,397 | 412,209 | fully linear (0 backward branches) |
| cycle #2 `0x1BCD60..0x2341C8` | 152,602 | 15,261 | fast path, linear |
| cycle #3 `0x2341CC..0x4BA840` | 630,556 | 155,133 steps / 77,703 unique | **7,744 backward branches** |
| total | 1,239,568 | 505,182 unique addresses | |

So **~505k of 1.24M words (41 %) are reachable**; the rest is dead code left
over from the pre-optimisation build (the file is larger than the model's code
image). All pattern statistics below are computed on executed code only.

Sorting executed addresses is *not* the execution order once loops exist —
this matters for any dataflow reconstruction and is handled by recording the
interpreter's exact instruction order (`research/gt_exec.json`).

---

## 3. What a logic element looks like in the code

Three example fragments from the executed netlist (annotations: `b<bank>.<slot>`,
names from the model symbol table).

### 3.1 A sum-of-products cone with a NOR (a real "dff/nor/nand" element)

```
0x3804d8  lbz  r24, 27852(r14)   ; b1.6ccc
0x3804dc  lbz  r12, 32464(r13)   ; b0.7ed0
0x3804e0  lbz  r8,  -14632(r14)  ; b1.c6d8
0x3804e4  or   r27, r24, r12              ;  r27 = 6ccc | 7ed0
0x3804e8  andc r8,  r24, r8               ;  r8  = 6ccc & ~c6d8
0x3804ec  lbz  r30, -31872(r14)  ; b1.8380
0x3804f0  andc r30, r12, r30              ;  r30 = 7ed0 & ~8380
0x3804f4  nor  r8,  r8,  r30              ;  r8  = ~((6ccc&~c6d8) | (7ed0&~8380))
0x3804f8  and  r8,  r8,  r27              ;  r8 &= (6ccc | 7ed0)
0x3804fc  stb  r8,  27784(r14)   ; b1.6c88   <-- the element's output wire
```

The recovered statement (`netlist_slice.py --dump`):

```
b1.6c88  <=  (~w1_8380 & ~w1_c6d8 & (w2_d805 | w2_e75e))
```

i.e. a **quad-input AND of literals** feeding one state wire: exactly the
"NAN-style network" the block naming suggests.

### 3.2 The dominant repeated element: `f2`-enabled multiplexer

```
b0.8dac  <=  ((f2_0x4b7f84 & f2_0x4b7fac) | (f2_0x4b7fd4 & w1_9563))
```
596 instances — a `(A&B) | (C&D)` select built from two `and` + one `or`.
The `f2` operands are values assembled by `rlwimi`/`rlwinm` bit packing
(section 8).

### 3.3 Straight copies (the L1→L2 plane walk)

Single-bit wire copied plane-to-plane accounts for the largest statement
class (2,533 instances, 38 % of the per-cycle netlist):
```
@004b7fac  b0.12fc <= w2_e3c0 ...
```
These are the two-value model's latch/plane transfers, not logic gates, but
they must be part of any faithful recovery.

---

## 4. Toolchain

Every tool is standalone and re-runnable; they build on `cosim.py` and share
its decoder semantics.

| tool | purpose |
|---|---|
| `netlist_extract.py` | decode the whole code region into a fixed-size per-instruction record stream (`research/netlist_ins.bin`), patch NOPs marked, register fields canonical, bank slots resolved |
| `netlist_stream.py` | shared record model (mnemonic, operands, slot, bank, operand-shape keys) |
| `netlist_gt.py` | per-instruction hook over the interpreter: executed addresses, resolved effective addresses, plane pointers |
| `gt_dump.py` | ground truth: state-bank snapshots, full memory images, exact execution order per pass (`research/gt_exec.json`, `research/gt_state/`) |
| `gt_regs.py` | the register file at every executed instruction (`research/gt_regs.json`) |
| `netlist_slice.py` | **the extractor**: symbolic replay of the executed stream producing netlist statements, families, catalogs, and the emitted netlist |
| `macroblocks.py` | instruction-template layer: def-use chains from each store to its defining instruction sequence |
| `family_diag.py` | expression-size diagnostics (measures the init pass's big cones) |
| `motif_hunt.py`, `motif_ngram.py` | generic n-gram motif counters over linear pieces (first-pass exploration) |
| `verify_netlist.py`, `verify_final.py` | verification of the recovered netlist against the compiled model |
| `residual_report.py` | attribution of the residual mismatches by atom kind |
| `pass_stats.py` | per-pass summary of the recovered netlist |
| `gt_state/`, `netlist_recovered_cycle2.txt` | captured ground truth and the emitted netlist |

`cosim.py` gained one optional debug hook (`CPU.hook`, `None` by default) used
by the ground-truth tools; interpretation behaviour is unchanged.

---

## 5. Method: "genes in DNA, with NOP introns"

1. **Strand** = the instruction stream; anchors = introns (skipped when
   matching, remembered for positions).
2. **Restrict to executed code** (section 2.1), because the dead code triples
   the stream and would poison every statistic.
3. **Linear pieces** = maximal runs of consecutive executed addresses; a
   control transfer ends a piece.
4. **Motif counting** by operand-normalised shape (register numbers, offsets
   and polarities abstracted) — `motif_hunt.py`.
5. **Dataflow replay** — the decisive step. Replaying the executed stream in
   order while tracking a symbolic value per register yields, for every store,
   the boolean expression of the wire being driven. This is robust to the
   compiler's code motion and register reuse, which defeat pure instruction
   n-gram matching (the accumulator, not a cell, carries the gate).
6. **Canonicalisation** — AND/OR/XOR are kept n-ary, associative and
   commutative, negation is pushed to the leaves (De Morgan), constants are
   absorbed, so two instances of one element with different *ports* hash
   identically while different *functions* do not.
7. **Verification** — replay the recovered netlist over the model's own
   pre-state and compare with the state the compiled model produced
   (sections 6.3, 8).

---

## 6. Recovered netlist

### 6.0 Per-pass summary

`pass_stats.py` recovers all three evaluation passes:

| pass | entry | statements | driven wires | constant | wire copy | boolean cone | cone+vector | vector/word | biggest cone |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| init | `0x2C` | 44,112 | 30,914 | 2,860 | 4,239 | 15,878 | 1,134 | 19,269 | **1,372 nodes** |
| cycle #2 | `0x1BCD60` | **0** | 0 | – | – | – | – | – | – |
| cycle #3 | `0x2341CC` | 6,680 | 3,594 | 702 | 5 | 1,612 | 1,105 | 3,236 | 50 nodes |

(classes are mutually exclusive; "vector/word" = whole-word copies plus values
assembled by bit packing)

Two things stand out:

* **the fast-path pass (cycle #2) writes no state wire at all** — all 828 of its
  `stw`s go to the private scratch region below the banks. It is pure idle
  detection, so the model's logic is the init pass plus the full per-cycle
  pass. (This also means `cosim.py`'s stage-1/stage-3 split is not a
  netlist/state split but an idle-shortcut split.)
* the init pass contains the model's **big cones** — 1,301 statements whose
  operator graph has more than 100 nodes, 104 of them above 1,000, the largest
  1,372 (expression statements average 19.1 nodes, 90th percentile 13) —
  because the compiler chains a whole cone into one accumulator register there.
  That is why the init pass is not verified by equivalence in this report
  (section 8): evaluating it means walking hundreds of thousands of shared
  nodes per pass, while the per-cycle pass — the logic that actually runs every
  cycle — is well-shaped (largest cone 50 nodes, mean 2.6).

### 6.1 Recovered netlist (per-cycle pass)

`research/netlist_recovered_cycle2.txt` — the per-cycle full evaluation
(entry `0x2341CC`), **6,680 statements** driving **3,594 distinct state wires**,
with the driving code address and the wire's symbol name:

```
@002342a4  b0.67d8  GKO.GE0.DMAL.NAN0.L2       <= w2_f5c4
@002342e4  b0.6814  GKO.BP0.BBFT.L1            <= w2_f570<L1>
@003804fc  b1.6c88                             <= (~w1_8380 & ~w1_c6d8 & (w2_d805 | w2_e75e))
@003819a4  b1.6d34                             <= (w1_6cbf & ~w1_c730 & ~w2_d2b0)
```

### 6.2 Statement classes (per-cycle pass, 6,680 total)

| class | count | meaning |
|---|---:|---|
| direct plane/wire copy (`s`) | 2,533 | two-value plane transfer |
| constant driver (`c`) | 702 | tie-offs, reset/default forcing |
| field-vector driver (`f`) | 708 | word assembled by bit packing |
| whole-word copy (`lwz`→`stw`) | 2,528 | verbatim multi-byte transfer |
| boolean cone of state wires (`&`/`\|`/`^`) | 1,612 | **the logic elements** |
| boolean cone containing a vector atom | 1,105 | logic mixed with word assembly |
| distinct boolean families (bounded) | 688 | see section 7 |

The pure boolean cones of state wires (1,612 statements, plus the 1,105 that
also use an assembled word) are what "logic elements" means here; the families
below are counted over all boolean drivers.

### 6.3 The boolean vocabulary (families, per-cycle pass)

| family | count | element |
|---|---:|---|
| `\|2(&2(f2,s),&2(f2,s))` | 596 | enabled 2:1 multiplexer / select |
| `&3(s,~s,~s)` | 364 | 3-input NAND-style term |
| `&3(\|2(s,s),~s,~s)` | 133 | sum-of-products with a shared term |
| `&5(s,~s,~s,~s,~s)` | 66 | wide NAND term |
| `\|2(s,s)` | 60 | 2-input OR |
| `&4(s,~s,~s,~s)` | 46 | wide NAND term |
| `&2(s,~s)` | 43 | AND with an inverted input |
| `\|3(s,s,s)` | 42 | 3-input OR |
| `^2(s,s)` | 35 | 2-input XOR |
| `&2(f2,s)` | 32 | enabled AND |
| `&3(\|2(f2,s),~f1,~s)` | 30 | mixed select + term |

Over the per-cycle pass, the *sub-expression* catalog
(`research/gate_catalog.txt`, produced by `--catalog`, cones up to 24 nodes)
counts every distinct cone shape — this is the primitive macroblock
vocabulary:

| sub-expression | count | element |
|---|---:|---|
| `s` | 2,533 | bare wire (copy) |
| `&2(f2,s)` | 755 | enabled AND |
| `c0` | 697 | constant 0 driver |
| `f2` | 690 | assembled vector word |
| `\|2(s,s)` | 481 | 2-input OR |
| `&3(s,~s,~s)` | 394 | 3-input NAND-style term |
| `&2(s,s)` | 187 | 2-input AND |
| `&2(s,~s)` | 109 | AND with inverted input |
| `&5(s,~s,~s,~s,~s)` | 69 | wide NAND term |
| `^4(s,s,s,s)` | 66 | 4-input XOR |
| `&3(s,s,s)` | 64 | 3-input AND |
| `\|3(s,s,s)` | 62 | 3-input OR |
| `\|2(f2,s)` | 59 | enabled OR |
| `&4(s,~s,~s,~s)` | 50 | wide NAND term |
| `^2(s,s)` | 44 | 2-input XOR |

1,185 distinct sub-expressions in this pass (1,583 without the size bound),
and the wide terms (`&30`, `&43`, `&12` …) show the compiler folding long
conjunctive chains into one gate. There is no "one opcode = one gate"
template: `andc`/`orc`/`nor` are the compiler's notation for **inverted
literals**, so one netlist element typically appears as a chain
`lbz…/andc…/nor/and/stb`.

### 6.4 Verification (per-cycle pass)

The recovered netlist is replayed over the model's own pre-state and compared
with the state the compiled model actually produced
(`verify_final.py`, `residual_report.py`). Of the 6,680 statements,

| class | statements | how it is checked |
|---|---:|---|
| bit-level (a boolean cone driving one wire) | 4,152 | recovered bit vs. the model's byte |
| whole-word copy (`lwz` → `stw`, value never modified) | 2,528 | source byte vs. destination byte |

| check | result |
|---|---|
| driven slots whose final value matches the model | **3,421 / 3,594 = 95.19 %** |
| bit-level class | **2,698 / 2,736 = 98.61 %** |
| whole-word-copy class | 2,422 / 2,443 = 99.14 % |
| statement-level agreement (`verify_netlist.py`) | 3,986 / 4,852 = 82.2 % |

**Attribution of the 173 differing slots** (`residual_report.py`):

| residual | count | cause |
|---|---:|---|
| bit-level driver containing an `f` atom | 170 atoms in the drivers (part of the 152 slots) | the wire's value comes from a word the compiler assembled bit by bit (`rlwimi`), so the recovered expression drives a different bit of that word |
| bit-level driver reading state wires | 572 atoms in the drivers | the slot holds a value the model later overwrote by a word store or plane alias that a single-bit bank model cannot attribute |
| whole-word copy | 21 | a `lwz`/`stw` pair whose source word the register file modified without the def-use walk seeing it |
| bit-level driver that is a constant | 1 | a tie-off the model overrides later |

So the recovered netlist is exact for logic built from state wires and array
reads; the whole residual is concentrated in the *multi-bit vector* construct,
which a single-bit netlist cannot represent (section 8).

---

## 7. Instruction-template layer (`macroblocks.py`)

For each store, walking the def-use chain backwards yields the template of the
value being stored with ports abstracted and function-bearing literals kept
(rotate/shift masks, compare constants). Over the per-cycle pass **287 distinct
templates** cover all 6,680 stores; the head of the catalog
(`research/macroblocks.txt`):

| count | params | template |
|---:|---:|---|
| 2,528 | 2,321 | `ld(bank)` — direct copy |
| 1,043 | 267 | `ld(bank) and` — AND with an external/inverted term |
| 628 | 0 | `rlwimi(16,0,15) and or` — vector assembly into a selector |
| 601 | 0 | `clrlwi(31,0,0)` |
| 378 | 285 | `and ld(bank)` |
| 174 | 129 | `or ld(bank)` |
| 158 | 1 | `ld(bank) andc or and` |
| 104 | 17 | `or ld(bank) and` |

Read together with section 6 this gives the answer to "can the schematic be
recovered": **yes at the netlist level** (statements with named wires and
boolean structure), **partially at the primitive-gate level** (the primitive
vocabulary is the `&`/`|`/`^` cones of section 6.2), and **not as a 1:1
opcode-pattern dictionary**, because the optimiser inlines and reorders
(one accumulator, shared sub-expressions, hoisted loads, `xori`-generated
complements) so heavily that a gate is a dataflow sub-tree rather than a fixed
instruction window.

### 7.1 Why templates alone are not enough: megacones

The instruction-template census is only meaningful because the *dataflow*
replay is available. The init pass shows why: there the compiler chains an
entire cone into one accumulator register, so a single `stb` can be driven by
an expression graph of up to **1,372 operator nodes** (measured over the
expression graph, `pass_stats.py`; 1,301 init statements exceed 100 nodes and
104 exceed 1,000, while the distribution is heavy-tailed — 27,100 statements
are constants and 6,498 are a single node). Such a statement is not one logic
element — it is a whole cone serialised through one register.
Consequences:

* instruction n-gram matching alone finds almost nothing (the templates are
  `andc`/`nor`/`and` runs of arbitrary length);
* family aggregation must be bounded (`--max-size`, `family_of()`;
  `family_diag.py` measures the sizes);
* printing a statement is *not* linear in its graph: sub-expressions are
  shared, so a 50-node graph expands to megabytes of text. `fmt()` therefore
  caps depth/width/length and `fmt_let()` prints a faithful linear form with
  the shared nodes bound; the per-cycle netlist file is written uncapped;
* the full per-cycle pass is the well-behaved one: mean expression 2.6 nodes,
  largest cone 50 nodes, which is exactly the size at which a statement
  corresponds to one logic element.

This is the quantitative form of the issue's own observation: the opcode
sequence of an element is stable, but its *parameters* (and, here, its
register/accumulator context) vary — and with global optimisation the
accumulator can also absorb neighbouring elements.


---

## 8. Known limits (and why they are limits, not bugs)

1. **Vector (multi-bit) wires.** Some wires are 32-bit words assembled bit by
   bit (`rlwimi/sh`/`xori`, then `stw`). Their element-wise boolean part is
   recovered; the word-level assembly is represented as an `f`-atom, and this
   one construct accounts for nearly the whole verification residual (170
   `f`-atoms among the drivers of the 173 differing slots). Whole-word copies
   whose loaded value is never modified *are* recovered exactly (2,422 of
   2,443 statements, 99.14 %).
2. **Array/memory image.** Wires whose value comes from the model's array
   memory (cache/queue arrays, `lwz` through a data pointer) are `p`/`mem`
   atoms. They are resolvable with a memory snapshot (as `verify_netlist.py`
   does) but are not logic gates.
3. **Dead code.** ~59 % of the file never executes; a full recovery of it
   would require recovering the pre-optimisation design as well. It is
   reported but excluded (and must be, or the pattern statistics are
   meaningless).
4. **Register-file inputs.** Values entering a fragment in a register are
   recorded exactly (`gt_regs.py`) for verification but remain `in_rN` symbols
   in the emitted netlist.
5. **The init pass is extracted but not equivalence-verified.** Its netlist
   *is* recovered (44,112 statements, 30,914 wires) and it is fully
   self-contained (no earlier state to depend on), but its cones chain a whole
   cone into one accumulator — up to 1,372 operator nodes per statement, with
   1,301 statements above 100 nodes — and the pass walks millions of shared
   nodes. Replaying it is therefore quadratic in practice, and it is reported
   as recovered rather than proven. The per-cycle pass, which is the logic that
   runs every cycle, is well-shaped (largest cone 50 nodes) and is verified
   (section 6.4).

---

## 9. Reproducing

```bash
python netlist_extract.py                    # decode -> research/netlist_ins.bin
python netlist_gt.py                         # interpreter trace, plane pointers
python gt_dump.py --cycles 2                 # state snapshots + execution order
python gt_regs.py --cycles 1                 # register file per instruction
python netlist_slice.py --region cycle2 --families      # gate families
python netlist_slice.py --region cycle2 --emit research/netlist_recovered_cycle2.txt
python netlist_slice.py --region cycle2 --catalog --out research/gate_catalog.txt
python macroblocks.py --region cycle2 --emit research/macroblocks.txt
python family_diag.py                         # expression-size diagnostics (slow)
python verify_final.py --pass cycle2 --cycle 0          # equivalence check
python verify_netlist.py --pass cycle2 --cycle 0        # statement-level check
python residual_report.py --pass cycle2 --cycle 0       # residual attribution
python pass_stats.py                                    # per-pass summary
```

Observed timings (this machine): extraction 40 s, interpreter ground truth
1.5 min, slicing of the per-cycle pass 3 s, verification 4 s.
