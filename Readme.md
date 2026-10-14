# Gekko COSIM

![gekkocore_icon.png](gekkocore_icon.png)

Contains a Python script for running the Gekko model `COSIM.m2630opt.Jul1599`, as well as the model specification and documentation for cosim.py

Enjoy!

## Macroblocks: recovering the logic elements from the compiled netlist

Issue [#1](https://github.com/ogamespec/gekko_cosim/issues/1) asks whether the
schematic can be recovered from the compiled PowerPC netlist, i.e. whether the
logic elements (`dff`, `nor`, `nand`, …) can be found as instruction patterns.
Answer and full method: **[research/GKO_MACROBLOCKS_Report.md](research/GKO_MACROBLOCKS_Report.md)**;
the recovered per-cycle netlist is
[research/netlist_recovered_cycle2.txt](research/netlist_recovered_cycle2.txt),
and the whole netlist split by original source module is in
**[research/modules/](research/modules/README.md)** (85 files, `<BLOCK>.txt`).

The tooling (all standalone, all built on `cosim.py`'s decoder):

| tool | purpose |
|---|---|
| `netlist_extract.py` | decode the whole code region into per-instruction records (`research/netlist_ins.bin`); patch NOPs flagged, registers canonical, bank slots resolved |
| `netlist_stream.py` | shared record/operand-shape model |
| `netlist_gt.py` | interpreter instrumentation (executed addresses, resolved addresses, plane pointers) |
| `gt_dump.py` | ground truth: state-bank snapshots, full memory images, exact execution order (`research/gt_state/`, `research/gt_exec.json`) |
| `gt_regs.py` | register file at every executed instruction (`research/gt_regs.json`) |
| `netlist_slice.py` | **the extractor**: symbolic dataflow replay -> netlist statements, gate families, catalogs |
| `macroblocks.py` | instruction-template census (def-use chains per store) |
| `family_diag.py` | expression-size diagnostics |
| `motif_hunt.py`, `motif_ngram.py` | generic opcode n-gram motif counters |
| `verify_netlist.py`, `verify_final.py` | verification of the recovered netlist against the compiled model |
| `residual_report.py` | attribution of the residual mismatches by atom kind |
| `pass_stats.py` | per-pass summary of the recovered netlist |
| `block_partition.py` | split the netlist into the original source modules (85 blocks) + coverage |
| `modules_split.py` | write the netlist as one file per module into `research/modules/` |
| `netlist_reach.py` | statically reachable vs. actually executed code and stores |
| `coverage_probe.py` | whether other stimulus recovers more of the netlist |
| `plane_report.py` | which L1/L2 plane each statement reads and writes |
| `pin_refs.py` | where the top-level pins are read in the netlist |

Completeness and module split are measured in
[research/GKO_NETLIST_COMPLETENESS.md](research/GKO_NETLIST_COMPLETENESS.md).

`cosim.py` gained one optional debug hook (`CPU.hook`, `None` by default, used
by the ground-truth tools); interpretation behaviour is unchanged.

Quick start:

```bash
python netlist_extract.py
python gt_dump.py --cycles 2
python gt_regs.py --cycles 1
python netlist_slice.py --region cycle2 --emit research/netlist_recovered_cycle2.txt
python netlist_slice.py --region cycle2 --families
python macroblocks.py --region cycle2 --emit research/macroblocks.txt
python verify_final.py --pass cycle2 --cycle 0
python residual_report.py --pass cycle2 --cycle 0
```
