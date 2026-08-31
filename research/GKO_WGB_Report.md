# Gekko Write Gather Buffer — Analysis Report

**Subject:** the write-gather pipe (Write Gather Buffer, WGB) of the IBM Gekko
microprocessor (GameCube CPU, MPC750-class core).
**Sources:** IBM Gekko RISC Microprocessor User Manual (Version 1.2, 5/25/00,
provided as `IBM Gekko RISC Microprocessor User Manual.pdf`), the compiled
logic model `model/COSIM.m2630opt.Jul1599` (MVLSIM), and the interpreter
`cosim.py` / test `wgb_bne_test.py`.
**Document version:** 1.0

---

## 1. Executive summary

1. The Gekko write-gather pipe is a **128-byte circular FIFO** plus the
   **WPAR** register (SPR 921) that gathers non-cacheable stores to one
   cache-line-aligned address and bursts them to memory.
2. **There is no timeout.** Data may sit in the buffer indefinitely. The
   buffer is flushed only by (a) accumulating **≥ 32 bytes** (automatic
   `write-with-flush` burst), (b) an **`mtspr` to WPAR** (invalidates the
   buffer), or (c) software **filling the block with dummy data**.
   `eieio`/`stwcx.`/`sync` have *no effect* on the pipe; the pipe does not
   participate in bus snooping. The only back-pressure is a **store stall
   when more than 120 bytes** are pending.
3. The compiled model **contains no timer** for the WGB: no
   `TIMEOUT`/`TMO`/`FLUSH`/`AGE` signals exist, the WGB counters are
   event-driven latches, and an injected "data present" state stays frozen
   for hundreds of idle cycles (no counter drain, no BNE clear, no burst
   request on the bus).
4. A software poll of `WPAR[BNE]` that observes BNE going to 0 "after some
   time" is best explained by **waiting for an already-triggered ≥32-byte
   flush to complete on the bus** (transfer latency), not by a timer.

---

## 2. Overview

The Gekko implements a write-gather pipe for efficient transfer of
non-cacheable data from the processor to external memory (e.g. the
GameCube's memory-mapped I/O and FIFO registers at `0x0C000000`). It
consists of:

* a **128-byte circular FIFO buffer** with independent read and write ports;
* the **Write Pipe Address Register (WPAR)**, SPR 921, holding the gather
  address and a "buffer not empty" status bit.

Non-cacheable stores to the address specified in WPAR are stored sequentially
into the buffer; once **32 bytes or more** have accumulated, the pipe
transfers the data to memory **32 bytes at a time** with
`write-with-flush` burst transactions.

---

## 3. Specification (IBM Gekko RISC Microprocessor User Manual)

### 3.1 WPAR register (Section 2.1.2.10, Table 2-18)

| Bits   | Name     | Description |
|--------|----------|-------------|
| 0–26   | GB_ADDR  | High-order address bits of the data to be gathered. The low-order address bits are zero, forcing the address to be **cache-line aligned**. Only these 27 bits are compared to decide whether a non-cacheable store will be gathered. |
| 27–30  | —        | Reserved |
| 31     | BNE      | **Buffer not empty** (read-only) |

WPAR is accessed with `mtspr`/`mfspr` using **SPR 921**. The pipe is enabled
by **HID2[WPE]** (SPR 920, bit 1): `0` = disabled at power-on, `1` = enabled.

### 3.2 Operation (Section 9.4.2)

* A `mtspr` to WPAR **invalidates the data in the buffer** and sets the
  gather address — all pending data is discarded, and subsequent
  non-cacheable stores to `WPAR[GB_ADDR] || 0b00000` are gathered.
* When ≥ 32 bytes are stored, the pipe transfers the data to memory
  32 bytes at a time with a `write-with-flush` burst at
  `WPAR[GB_ADDR] || 0b00000`.
* Software checks `WPAR[BNE]` to determine whether the buffer is empty.
* **`eieio`, `stwcx.`, and `sync` have no effect on the write gather pipe.**
* The pipe **does not participate in bus snoop** operation.
* **The only way for software to flush a partially full 32-byte block is to
  fill the block with dummy data** (which the consumer must recognize or
  ignore).
* A non-cacheable store to an address matching `WPAR[GB_ADDR]` in bits 0–26
  but with bits 27–31 **not all zero** results in **incorrect data** in the
  buffer.

### 3.3 Timing (Section 9.4.3)

* The buffer has **independent read and write ports**, so a burst transfer
  does not block store instructions.
* **However, when the buffer has more than 120 bytes pending, a
  non-cacheable store to the gather address stalls** (back-pressure, not a
  timeout).
* The cycle following a store that makes the buffer contain **at least
  32 bytes**, a transaction request is made to the BIU to burst out 32 bytes.
  A second request can be made as soon as the first is being served and
  another 32 bytes have been gathered.
* The BIU serves transaction requests from multiple sources (DMA write,
  instruction load, …) on a first-come-first-served basis.

### 3.4 Related: Integer Store Gathering (Section 2.3.4.3.5)

Separate from the WGB, the LSU merges **two consecutive word-aligned 4-byte
stores** into a doubleword for write-through / cache-inhibited stores to
nonguarded space (enabled by **HID0[SGE]**). This small-scale gathering is
not performed for cacheable stores, guarded accesses, byte-reverse stores,
`stwcx.`/`ecowx`, floating-point stores, or hardware-table-search accesses;
the manual notes that the WGB "provides a separate mechanism for gathering
operands before transferring them to memory" (see Appendix A.3).

---

## 4. Implementation in the compiled model

Location of the write-gather-pipe logic in `COSIM.m2630opt.Jul1599`
(signal names from the model symbol table; slots are 16-bit state slots):

| Block | Signals | Role |
|-------|---------|------|
| `GE0` | `WPAR.NAN0..7` (slots 0x6980–0x69E0 L1, 0x6B08–0x6B20 L2, 0xFF67/0x286B CR) | WPAR register (SPR 921) |
| `GE0` | `WPC*` (`WPCA..WPCK`, `WPCL/WPCF..WPCJ`; slots 0xE8D8–0xEA50, 0x6EEB–0x7AEB) | write-pipe counters / rotating pointers |
| `GE0` | `QNTR0..7` (slots 0x0068–0x6B00) | queue/status counters (event latches) |
| `GE0` | `HID_G_REG` | HID register (contains HID2[WPE]-class enable state) |
| `HIC` | `HID2.BIT0..2` (slots 0x0B5F/0x0C5F/0x0D5F L1) | HID2 — **bit 1 = WPE** (write-pipe enable) |
| `LAS` | `CSQ_ST_GATHER`, `HSQ_ST_GATHER`, `ST_GATHER_EF/FC` (slots 0x5082/0xA984, 0xAA82/0xC483, 0xAE83/0xAF83/0xE583/0xE683) | store-queue gather flags |
| `LAS` | `FSQ_*`, `CSQ_*`, `HSQ_*` (addresses, byte enables `ST_BEN`, sizes `ST_SIZE`, tags, `STRING/SYNC/EIEIO/RSRV`) | store queues feeding the pipe |
| `DLS` | **`WP_REQ_QUAL`** (slot 0x773A) | **write-pipe burst request qualify** — the flush request to the BIU |
| `DLS` | `TLD_REQ`, `LD_REQ`, `DCBZ`… | cache/load-store request control |
| BIU | `BAC` (`AT_LAT`, `SNPI_LAT`, `RETRY`, `KILL`, `L2CST`), `BDT` (`ALAT`, `OE_LAT`, `ARTRY`), `BDR` (`RLD_LAT`, `RUNQ_LAT`) | address/data tenures for the burst |

Key facts from the decompiled logic (see `model/WGB_logic_decompile.txt`,
1751 lines, generated by `decompile_model.py`):

* The `GE0.WPC*` counters are **latch-with-hold** cells of the form
  `Q <= (new & sel & ~hold) | (Q & hold)` — they update only on events
  (store accepted, 32-byte flush, `mtspr`), never on a free-running clock.
* The `GE0.QNTR0..7` file is a set of event-driven status counters
  (`Q <= (A | (B & ~C)) & ~D`), sourced from DMA, WPAR, store queues and
  bus events.
* The flush request `DLS.WP_REQ_QUAL` is an OR of several request
  conditions from different sources (DMA / store queues / L2) — no
  time/counter input appears in its cone.
* The `mtspr` WPAR path copies the SPR write data bus into the register
  (cells at 0x2345F0–0x234A00).

**No `TIMEOUT`, `TMO`, `FLUSH`, `AGE`, `STALE` or similar signal exists in
the whole model (16,865 named signals), and no assert message mentions a
gather timeout.**

---

## 5. The timeout question — evidence

### 5.1 Manual

Section 9.4 documents **no timeout**; the only flush mechanisms are the
≥ 32-byte rule, `mtspr` to WPAR, and dummy-data fill (see Appendix A).

### 5.2 Model

Static analysis found no timer in the WGB logic (Section 4).

### 5.3 Empirical test (`wgb_bne_test.py`)

The test injects a "data present" WGB state (HID2[WPE]=1, WPAR address,
byte counter = 24 — a partial block — write-pipe pointers, LAS gather
flags) and runs **400–500 idle cycles** with no new stores and no bus
traffic, watching the byte counter, the BNE bit and the `TS_` pin:

```
start: WPC counter = 24, WPAR.NAN7(BNE?) = 1
cyc    0: WPC= 24 BNE=1 TS_=0
cyc  100: WPC= 24 BNE=1 TS_=0
cyc  200: WPC= 24 BNE=1 TS_=0
cyc  399: WPC= 24 BNE=1 TS_=0
RESULT: state frozen — no time-based flush observed
```

The injected state neither drains nor flushes during idle. This is
consistent with "no timeout", but note the caveat: state injection does not
guarantee the model treats the buffer as *fully valid with data*, so this is
strong but not absolute evidence (a full program-driven test requires exact
60x bus-handshake timing).

### 5.4 Interpretation of the Mario Sunshine observation

Mario Sunshine polls `WPAR[BNE]` after issuing stores to the gather address.
If the stores total ≥ 32 bytes, the flush burst is requested the very next
cycle (Section 9.4.3) and the poll simply waits for that in-flight burst to
complete — BNE clears when the last byte leaves the buffer, i.e. after the
**bus transfer latency**, not after a timer. If a *partial* block (< 32
bytes) were observed to clear without a WPAR rewrite, that would contradict
both the manual and the model; in that case the game is likely performing a
WPAR rewrite or the flush is triggered by another bus participant.

---

## 6. Conclusions

1. **No timeout** on data in the Gekko write gather buffer — per the IBM
   manual and per the compiled model.
2. Flush conditions: **≥ 32 bytes** accumulated, **`mtspr` to WPAR**,
   **dummy-data fill**. `sync`/`eieio`/`stwcx.` do not flush it.
3. Software that must guarantee delivery of a partial block must either
   write WPAR (flush + re-arm) or pad the block to 32 bytes.
4. The observed "BNE → 0 after some time" behavior in game code is the
   completion latency of an already-started burst, not a timer.

---

## Appendix A. Reference — specification text

Extracted from `IBM Gekko RISC Microprocessor User Manual.pdf`
(Version 1.2, 5/25/00). Text is reconstructed from the PDF content streams
(character-level kerning merged); ligatures/spacing normalized.

### A.1 Section 9.4 — Write Gather Pipe (pages 9-10 … 9-11)

> Gekko implements a write gather pipe for efficient transfer of
> non-cacheable data from the processor to the external memory. The write
> gather pipe consists of a **128-byte circular FIFO buffer** and a special
> purpose register: Write Pipe Address Register (WPAR). For a non-cacheable
> store instruction to the address specified in WPAR, the operand will be
> stored sequentially in the buffer. **When there are 32 bytes or more of
> data in the buffer, the write gather pipe will sequentially transfer the
> data to the external memory by burst transaction.**
>
> **9.4.1 WPAR** — The write gather pipe address register is a 32-bit
> special purpose register. WPAR holds the upper 26 bits of the physical
> address of the write pipe, WPAR[GB_ADDR], and a status bit, WPAR[BNE]. The
> WPAR controls the operations of the write gather pipe.
>
> **9.4.2 Write Gather Pipe Operation** — The write gather pipe is disabled
> at power-on as HID2[WPE] = 0. Setting HID2[WPE] = 1 enables the write
> gather pipe. A `mtspr` to WPAR **invalidates the data in the buffer** and
> sets the gather address. In other words, all the data in the buffer, yet
> to be transferred, will be discarded and the operand of all the store
> instructions to the non-cacheable address of WPAR[GB_ADDR] || 0b00000 will
> be stored in the buffer. When there are 32 bytes or more of data stored in
> the buffer, the write gather pipe will transfer the data to the memory
> 32 bytes at a time with a **write-with-flush burst transaction**. The
> address of the transaction is WPAR[GB_ADDR] || 0b00000. Software can check
> WPAR[BNE] to determine if the buffer is empty or not. **The `eieio`,
> `stwcx.`, and `sync` instructions have no effect on the write gather
> pipe.** The write gather pipe does not participate in bus snoop operation.
> **The only way for software to flush out a partially full 32-byte block is
> to fill up the block with dummy data.** This fill data must be recognized
> or ignored by the consumer of the data stream to ensure the system's
> proper behavior. A non-cacheable store to an address with bits 0–26
> matching WPAR[GB_ADDR] but with bits 27–31 not all zero will result in
> incorrect data in the buffer.
>
> **9.4.3 Write Gather Pipe Timing** — The buffer of the write gather pipe
> has independent read and write ports such that the burst transfer does not
> block the store instructions. **However, when the buffer has more than
> 120 bytes of data pending to be transferred, a non-cacheable store
> instruction to the gather address stalls.** The cycle following a store to
> the write gather pipe such that the buffer contains at least 32 bytes, a
> transaction request is made to the BIU to burst out 32 bytes of data. As
> soon as the write transaction request is being served by the BIU, a second
> write transaction request can be made to the BIU, if an additional
> 32 bytes has been gathered. On a first-come-first-serve basis, the BIU
> serves transaction requests from multiple sources, e.g., DMA write,
> instruction load, etc.

### A.2 Table 2-18 — Write Pipe Address Register Bit Settings

> | Bits | Name | Description |
> |------|------|-------------|
> | 0–26 | GB_ADDR | High order address bits of the data to be gathered. The low order address bits are zero, forcing the address to be cache line aligned. Note that only these 27 bits are compared to determine if a non-cacheable store will be gathered. If the address of the non-cacheable store has a non-zero value in the low order five bits, incorrect data will be gathered. |
> | 27–30 | — | Reserved |
> | 31 | BNE | Buffer not empty (read only) |

WPAR is accessed with `mtspr` and `mfspr` using **SPR 921**.

### A.3 Section 2.3.4.3.5 — Integer Store Gathering

> Gekko performs store gathering for write-through accesses to nonguarded
> space or to cache-inhibited stores to nonguarded space if the stores are
> 4 bytes and they are word-aligned… [the LSU merges two stores into] a
> doubleword and [sends them] out on the 60x bus as a single-beat
> operation. However, stores can be gathered only if the successive stores
> that meet the criteria are queued and pending. Store gathering takes place
> regardless of the address order of the stores. The store gathering feature
> is enabled by setting **HID0[SGE]**. Store gathering is done for both big-
> and little-endian modes. Store gathering is **not** done for the
> following: cacheable stores; stores to guarded cache-inhibited or
> write-through space; byte-reverse stores; `stwcx.` and `ecowx` accesses;
> floating-point stores; store operations attempted during a hardware table
> search. If store gathering is enabled and the stores do not fall under the
> above categories, an `eieio` or `sync` instruction must be used to prevent
> two stores from being gathered. **Note that the write gather pipe
> facility provides a separate mechanism for gathering operands before
> transferring them to memory.**

---

## Appendix B. Test harness

* `wgb_bne_test.py` — injects a WGB "data present" state and checks whether
  it drains/flushes over idle cycles (used for Section 5.3).
* `model/WGB_logic_decompile.txt` — decompiled WGB logic cells (GE0/LAS/DLS)
  referenced in Section 4.
