# cosim.py — a limited-but-sufficient interpreter for the GKO MVLSIM model

`cosim.py` runs the logic model `COSIM.m2630opt.Jul1599` (IBM GKO, a PowerPC-class
processor) **without** MVLSIM itself. It contains a small PowerPC interpreter
(exactly the instruction subset used by the model), the model's state banks, the
pin table, the assert-message table, and the patch-list handling.

```
python3 cosim.py -m model/COSIM.m2630opt.Jul1599 \
                 -p model/pin.list \
                 -i inputs.txt -n 100 -o sim.log -d sim.dump
```

## What it does per cycle

1. Applies the input pins from the per-cycle input map to the state banks
   (each pin bit is written to both of its table slots, in all 8 banks).
2. Runs the model code from its per-cycle entry `0x1BCD60` (bootstrap #2) down
   to the final `blr` at `0x4BA83C` (return to the caller):
   * register setup (r13–r20 = 8 state banks, call block at address 0),
   * cell evaluation: `lbz`/`and`/`or`/`andc`/`nor`/`stb` … combinational cones,
   * priority decoders (`cmplwi`/`cmplw` + `bne`/`b`), bit packing
     (`slwi`/`rlwimi`), jump-table dispatches (`mtlr`/`blr`),
   * assert cells: they write the **message offset** into slot `0x8040`
     (call-block +0x40) and call the MVLSIM assert printer (descriptor in
     call-block +0x5C / slot `0x805C`) via `mtlr`+`blrl`. `cosim.py` decodes
     the offset into `"<sev> | <path> >  <text>"` from the model's message
     region (`0x515FB6`).
3. Reads the output pins (monitoring) and dumps all named signals.

At load time bootstrap #1 (`0x2C`) is run once (init pass, sets constant wires).

## Input file format (per-cycle pin map)

```
# comment
<cycle>[:<cycle_end>] <PIN>=<value> [<PIN>=<value> ...]
```

* value `0`/`1` for single-bit pins, `0xNN`/`NN` for buses; `-` = keep previous.
* pins not mentioned keep their previous value (initial 0).
* `*` repeats the previous line for the next cycle.
* data-bus words (DH/DL) are just bus values — put your "PowerPC program"
  words on DH/DL during the fetch handshake.
* `python3 cosim.py --gen-input template.txt -n 40` writes a reset+idle template.

## Outputs

* `-o log`: per-cycle named-signal summary, input/output pin values, asserts,
  diagnostics (mem-fault count, changed named signals), final summary.
* `-d dump`: per-cycle dump of **all** named slots (slot, name, value) — use
  `--dump-changed-only` to dump only the signals that changed that cycle.
* `--maxasserts N`: print details for the first N asserts (default 3, like the
  original `-maxasserts 3`); all asserts are still counted.
* `--verbose`: print the **known cell name** of every load/store that touches a
  state-bank slot, marked `Load`/`Store` (e.g.
  `Store @0x12bc1c stb  GKO.CCC.RNBUFF1.BIT0.L1 (slot 0xe95e) = 1`). Combine
  with `--verbose-max N` to cap the printed accesses per pass.

## Options

| option | meaning |
|---|---|
| `-m/--model` | model file (default `model/COSIM.m2630opt.Jul1599`) |
| `-p/--pinlist` | pin.list file |
| `-i/--inputs` | per-cycle input map (txt) |
| `-n/--cycles` | number of cycles (default 100) |
| `-o/--log`, `-d/--dump` | log / per-cycle dump files |
| `--no-init` | skip the one-time init pass (bootstrap #1) |
| `--maxsteps N` | instruction cap per pass (diagnostics for hangs) |
| `--trace N` | print the first N instructions of each pass |
| `--verbose` | print known cell names on load/store accesses (Load/Store) |
| `--verbose-max N` | cap verbose accesses printed per pass |
| `--debug` | hot-address / wrap diagnostics |
| `--gen-input FILE` | write a template input map and exit |
| `--dump-changed-only` | dump only changed slots per cycle |

## How the reverse-engineering facts are encoded

* entry points: header `+0x80` = `0x1BCD60` (per-cycle), `+0x70` = `0x2C` (init);
* patch list: all 38,738 nodes (walked back from `0x4BA800`) become NOPs;
* call block at address 0: `+0x00..+0x18C` = MVLSIM function descriptors
  (assert printer = `0x10007624` …), `+0x10` = model base (0), `+0x40` =
  assert message offset, `+0x68` = saved registers (`stmw`/`lmw` frame);
* state: 8 banks × 0x10000 bytes, 1 byte per wire, slot = displacement
  (negative displacements fold into 0x8000–0xFFFF);
* pins: table `0x5155EF..0x515FA6` — pairs of slots per bit, order == pin.list.

## Known limitations (limited-sufficient)

* memory arrays (caches / buffers) stay zero: pointer dereferences that in
  MVLSIM hit the test-bench heap are reported as `mem-faults` and read 0;
* initial latch state is zeros + bootstrap #1 constants (the model's own
  initial-state list is not applied);
* the exact mvlsim assert line prefix is not reproduced; text and path come
  from the model;
* ~30–40k instructions per cycle ⇒ ~0.1 s/cycle in CPython (usable for
  hundreds of cycles; the full 8548-cycle original run would take hours).
