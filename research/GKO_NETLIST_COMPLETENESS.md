# Netlist completeness and module split — measurements

This note records the measurements that answer two questions about the
recovered netlist (issue #1 tooling, see `GKO_MACROBLOCKS_Report.md`):

1. can the netlist be split back into the original source modules?
2. is this the whole netlist, or is part of it missing?

All numbers below come from `block_partition.py`, `netlist_reach.py`,
`coverage_probe.py` and `plane_report.py`; the model is
`model/COSIM.m2630opt.Jul1599` with the interpreter `cosim.py`.

---

## 1. Split into the original modules

**Yes, at the top-level block granularity** — the design hierarchy survives in
the model's symbol table as `GKO.<BLOCK>.<signal>…`: **85 top-level blocks**,
which are the `*.dsl` source files the issue refers to.

Two attribution channels are used, because the compiler names only a minority
of the wires:

| channel | statements | how |
|---|---:|---|
| wire symbol name | 14,427 (28.4 %) | the driven wire is `GKO.<BLOCK>…` |
| **code address** | 36,223 (71.3 %) | the wire is a nameless local cone; the block is taken from the dominant named destination of the 4 KiB code bucket the store executes from |
| unattributed | 142 (0.3 %) | neither channel resolves |

The code-address channel works because the compiled code is laid out block by
block — the same observation `research/GKO_CODE_MAP.md` was built on. Result:

| block | role | statements | share | from init | from per-cycle |
|---|---|---:|---:|---:|---:|
| L20 | L2 cache | 16,209 | 31.9 % | 15,523 | 686 |
| IC0 | I-cache array | 4,782 | 9.4 % | 4,764 | 18 |
| LAS | LSU datapath | 3,433 | 6.8 % | 3,241 | 192 |
| CCC | completion / rename | 2,279 | 4.5 % | 2,198 | 81 |
| HA0 | array slices | 2,030 | 4.0 % | 132 | 1,898 |
| MM0 | MMU arrays | 1,830 | 3.6 % | 1,823 | 7 |
| GE0 | SPRs / counters | 1,807 | 3.6 % | 1,605 | 202 |
| QSR | status/queue regs | 1,569 | 3.1 % | 1,564 | 5 |
| HE0 | LSU/exec slices | 1,173 | 2.3 % | 287 | 886 |
| WA0 | ECID / SPRs | 1,129 | 2.2 % | 1,076 | 53 |

(full table: `python block_partition.py`; grouped file:
`research/netlist_by_block.txt`)

**The netlist itself is split into one file per module** in
[`research/modules/`](modules/README.md) — 85 files named `<BLOCK>.txt`, each
with its statements (init + per-cycle), the code address, the wire and the
recovered expression.  Written by `python modules_split.py`; the per-file
counts are indexed in [modules/README.md](modules/README.md).

**Limits of the split:**
* it is a *flat* per-block grouping, single level — the `GKO.<BLOCK>.<sub>`
  naming could in principle give a second level, but most wires are nameless,
  so a deeper split would be guesswork;
* 84 of the 85 blocks have at least one driven wire; `LEC` has none (no wire
  in that block is written in any executed path).

---

## 2. Is this the whole netlist?

### 2.1 Complete for what the model actually runs

| check | result |
|---|---|
| bank-store instructions in the executed trace | 50,792 |
| statements in the recovered netlist | 50,792 |
| **ratio** | **100.0 %** |
| distinct (bank, slot) wires written | 34,081 |
| wires covered by the netlist | 34,081 (100.0 %) |

So for the code the model executes, nothing is missing.

### 2.2 But the model executes only part of its code

`netlist_reach.py` walks the code statically from the three entry points
(`0x2C`, `0x1BCD60`, `0x2341CC`) following fall-through and every branch
target:

| quantity | count | share |
|---|---:|---:|
| words in the code region | 1,239,557 | 100 % |
| statically reachable from the entries | 1,077,808 | 87.0 % |
| actually executed | 505,173 | 40.8 % of the file, 46.9 % of reachable |
| bank-store instructions, statically reachable | 102,228 | |
| bank-store instructions, executed | 50,792 | 49.7 % |
| **reachable but never executed** | **68,731** | 67.2 % of reachable |

### 2.3 The executed path does not depend on the input at all

This is the decisive measurement. Three runs of the model — no pin stimulus,
all bus pins driven to 0, all driven to 1 (and a 12-cycle run with randomised
`A/DH/DL/TT/TS_/BR_/BG/INT_…`) give *identical* coverage:

```
no stimulus        addresses  505182   bank-store sites  50793
all pins 0         addresses  505182   bank-store sites  50793
all pins 1         addresses  505182   bank-store sites  50793
random, 12 cycles  addresses  505182   bank-store sites  50793   (no growth after cycle 2)
```

So the 50,793 store sites are exactly the netlist the model contributes
through the banks, for every pin pattern — the remaining 68,731 store
instructions are not reachable by stimulus. They sit in large contiguous
unused islands (e.g. `0x1F1D1C..0x2341A0`, `0x08CD6C..0x0B6418`,
`0x3CE98C..0x3DE4B0`), consistent with the earlier finding that the file
carries a superseded build whose cells are only partly overwritten by the
runtime patch list.

**Conclusion.** The recovered netlist is the *complete* bank-level netlist of
the model's per-cycle logic. What is *not* in it:

* the never-executed code islands (≈68.7k store instructions) — a second,
  unused configuration in the same file;
* the model's **array memory** (caches, queues, register files, 5 MB of state
  memory) — that belongs to the MVLSIM test bench, not to the compiled logic,
  and the netlist reads it through pointer loads (`mem_rN[...]`, section 8 of
  the main report).

---

## 3. Reproducing

```bash
python block_partition.py                     # module split + coverage
python block_partition.py --emit research/netlist_by_block.txt
python modules_split.py                       # -> research/modules/<BLOCK>.txt
python netlist_reach.py                       # reachable vs executed
python coverage_probe.py --cycles 12          # stimulus-independence
python plane_report.py                        # which plane each statement uses
python pin_refs.py --region cycle2            # pin slots in the netlist
```
