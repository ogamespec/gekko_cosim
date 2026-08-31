# COSIM.m2630opt.Jul1599 — Compiled Model File Specification

**Document version:** 2.0 (updated with the `cosim.py` interpreter findings)
**Subject:** `model/COSIM.m2630opt.Jul1599` — compiled logic model of the **GKO (Gecko)** PowerPC-class processor for the **MVLSIM V1.7** logic simulator.
**File size:** 5,737,028 bytes (0x578A44)
**Build stamp:** 07/15/99 15:12:45 (this is the `Jul1599` build)
**Format version:** 17 (0x11)

> All findings in this document were obtained by reverse-engineering the
> MVLSIM loader/simulator (`mvlsim`, AIX/RS6000 COFF, not stripped) and by
> direct analysis of the model file. Notation: all offsets are file-relative
> unless stated otherwise; multi-byte integers are **big-endian**.
>
> **What changed in v2.0:** exact per-cycle call convention and call-block
> layout (§5), the instruction set actually used (§6), the real assert
> mechanism (§8 — replaces the old "assertion table" section, which was in
> fact the pin table), the fully decoded pin-table encoding (§9), corrected
> counts and file-layout boundaries (§2, §3, §10). All of it is verified by
> the working interpreter `cosim.py` (see §13).

---

## 1. Overview

`COSIM.m2630opt.Jul1599` is a **compiled (native) PowerPC model**: its
executable part is real PowerPC code that evaluates the processor's logic
cycle by cycle. The model is *not* a netlist and contains *no* readable text
until decoded: all names live in a compressed symbol table, all messages in a
string region, and the logic is a flat sequence of straight-line
"evaluation cells".

Key properties reported by the loader (`COSIM.sim` log):

```
The model is non-parallelized, two-value and non-transparent.
Model is /home/cosim/model/COSIM created on 08/05/99 at 15:51:38, 5775060 bytes.
```

Model type: **"ppc"** (load-type code 6, `sim→0x1564`). A different patch
behaviour applies to type "630"/"sj" and to models loaded with
`-PREFETCH_ENABLE` (`sim→0x156c`).

The model contains **no `bl` and no traps** anywhere in the code region:
execution is a linear cell walk driven by jump-table dispatchers, and the
only indirect calls are the **assert-printer** calls (§5.4, §8).

---

## 2. File Layout

```
Offset          Size       Contents
─────────────────────────────────────────────────────────────────────
0x000000        0x4BA800   Compiled model code/data:
                           - entry `b 0x28`, two dcbt helpers (0x00..0x2B)
                           - bootstrap #1 / init entry (0x2C .. 0x1BCD5C)
                           - bootstrap #2 / per-cycle entry (0x1BCD60)
                           - bootstrap #3 (0x2341CC)
                           - ~38,600 evaluation cells (0x80-byte seams,
                             patch-slot word at each seam) + jump tables
0x4BA800        0x40       Patch-list chain (embedded in code)
0x4BA840        0x5ADAF    Symbol records (classes A/B), 0x4BA840 .. 0x5155EF:
                           - the header declares 0x5B76C bytes (0x4BA840 ..
                             0x510FAC) and 0x50D3 records as bounds;
                           - the records actually run to ~0x5155EA (right
                             before the pin table); the tail holds more
                             class-B records — LSSD / shift-chain register
                             names such as "U.ABCD.L2", "…CA.BIT0.L1"
0x5155EF        0x1B7      Pin table (41 chip pins) — see §9
0x515FA6        0x10       gap / tail
0x515FB6        0x624BD    Message/assert strings + DSL paths — see §10
0x5789A8        0x9C       Trailer header (end of file) — see §3
─────────────────────────────────────────────────────────────────────
```

---

## 3. Trailer Header (0x9C bytes at end of file)

The header is located at `file_size − 0x9C` = **0x5789A8**.

### 3.1 Raw hexdump

```
005789a8: 00 4b a8 00 00 00 f2 00 00 00 00 00 00 00 00 4c  |.K.............L|
005789b8: 00 00 00 00 00 00 00 11 00 00 00 4a 00 00 00 9c  |...........J....|
005789c8: 31 32 33 34 f1 f2 f3 f4 30 37 2f 31 35 2f 39 39  |1234....07/15/99|
005789d8: 31 35 3a 31 32 3a 34 35 00 00 00 00 00 4b a8 40  |15:12:45.....K.@|
005789e8: 00 05 b7 6c 00 00 50 d3 00 40 ba ac 00 00 00 21  |...l..P..@.....!|
005789f8: 00 00 0a 49 00 40 b6 ac 00 03 47 00 00 00 04 00  |...I.@....G.....|
00578a08: 00 00 05 35 00 00 00 00 00 00 00 00 00 00 00 02  |...5............|
00578a18: 00 00 00 2c 00 23 41 cc 00 00 00 2c 00 00 00 2c  |...,.#A....,...,|
00578a28: 00 1b cd 60 00 51 5f b6 00 00 00 00 00 00 01 98  |...`.Q_.........|
00578a38: 00 51 5f b6 00 06 24 bd 00 00 10 00              |.Q_...$.....|
```

### 3.2 Field table

All offsets are relative to the header start (0x5789A8). "→ sim" is the
destination field of the simulator's model structure.

| Off | Value | → sim | Meaning |
|----:|-------|-------|---------|
| 0x00 | `0x004BA800` | (walk) | **Patch-list head offset** (file-relative) |
| 0x04 | `0x0000F200` | 0x858 | **State-block size** (61,952) — copied by bootstrap #3 |
| 0x08 | 0 | 0x860 | reserved |
| 0x0C | 76 | 0x864 | reserved |
| 0x10 | 0 | 0xA7C | reserved |
| 0x14 | **17** | 0x7F8 | **Format version** (0x11 ⇒ MVLSIM V1.7) |
| 0x18 | **0x4A** | 0x80C,0xA8C,0xA64,0xA74 | **Model flags** (see 3.3) |
| 0x1C | 0x9C | (size) | Header size (156) |
| 0x20 | `0x31323334` | check | **Magic "1234" (ASCII)** — byte-order marker |
| 0x24 | `0xF1F2F3F4` | check | **Magic "1234" (EBCDIC)** — string-encoding marker |
| 0x28 | `"07/15/99"` | 0x7FC | **Build date** (8 ASCII bytes) |
| 0x30 | `"15:12:45"` | 0x804 | **Build time** (8 ASCII bytes) |
| 0x38 | 0 | 0x810,0x54 | Value code (0 = two-value) |
| 0x3C | `0x004BA840` | 0x830 | **Symbol section offset** |
| 0x40 | `0x0005B76C` | 0x834 | **Symbol section size** (374,636) |
| 0x44 | `0x000050D3` | 0x86C | **Symbol count** (20,691) |
| 0x48 | `0x0040BAAC` | 0x874 | End offset of code/data block |
| 0x4C | 33 | 0x968 | counter (33) |
| 0x50 | 2,633 | 0x924 | counter (2,633) |
| 0x54 | `0x0040B6AC` | 0x83C | Start offset of code/data block |
| 0x58 | `0x00034700` | 0x850 | block offset (214,784) |
| 0x5C | 1,024 | 0x854 | block size |
| 0x60 | 1,333 | 0xA84 | gap between end of strings and header |
| 0x64 | 0 | 0x884 | reserved |
| 0x68 | 0 | 0x888 | reserved |
| 0x6C | **2** | 0x880 | **stride count** (2 ⇒ latch phases L1/L2) |
| 0x70 | 44 | 0x820 | **bootstrap #1 offset = 0x2C (init entry)** |
| 0x74 | `0x002341CC` | 0x828 | **bootstrap #3 offset** (state-block copy) |
| 0x78 | 44 | (—) | bootstrap #1 offset again |
| 0x7C | 44 | 0x824 | bootstrap #1 offset again |
| 0x80 | `0x001BCD60` | 0x82C | **per-cycle ENTRY (bootstrap #2)** — used by the first `.txcall` of every cycle |
| 0x84 | `0x00515FB6` | — | end of symbol section (= messages start) |
| 0x88 | 0 | — | reserved |
| 0x8C | 408 | 0x840 | counter |
| 0x90 | `0x00515FB6` | 0x868 | **Messages offset** (base used by the assert printer) |
| 0x94 | `0x000624BD` | (count) | **Messages size** (402,621) |
| 0x98 | 4,096 | 0x6CC | parameter |

### 3.3 Flags word (offset 0x18 = 0x4A = `0100_1010`)

| Bit | Destination | Meaning |
|----:|-------------|---------|
| 0 | `0xA64` (inverted) | "parallelized" flag (0 ⇒ non-parallelized) |
| 1 | `0xA74` | "transparent" flag (0 ⇒ non-transparent) |
| 3 | `0x80C`, `0xA8C` | mode select — **for this model both = 1, so the second per-cycle `.txcall` is skipped (§5.1)** |
| 28..31 | (branch) | `> 0` enables the patch-list pass (4 here) |

### 3.4 Worked example

```
Header field 0x3C: bytes 00 4b a8 40  => offset 0x4BA840
  => the symbol table begins at file offset 0x4BA840.
Header field 0x80: bytes 00 1b cd 60  => per-cycle entry 0x1BCD60.
Header field 0x90: bytes 00 51 5f b6  => messages at 0x515FB6.
Header field 0x14: bytes 00 00 00 11  => version 17.
Header field 0x20/0x24: "1234" (ASCII) + "1234" (EBCDIC): byte order is
  big-endian and strings are ASCII (no EBCDIC conversion at load).
```

---

## 4. Patch List

### 4.1 Node format

Every node is a 32-bit word:

```
bits 31..2  offset of the NEXT node, relative to file start (0 ⇒ end)
bits  1..0  tag (patch type)
```

The chain runs **backwards** (from the end of the code to the beginning):

```
0x004BA800  0x004BA782  tag=2  next=0x004BA780
0x004BA780  0x004BA702  tag=2  next=0x004BA700
...
0x00000028  0x00000017  tag=3  next=0x00000014
0x00000014  0x00000005  tag=1  next=0x00000004
0x00000004  0x00000000  tag=0  next=0x00000000   (end)
```

Total: **38,739 nodes** (38,738 link words + the end node); tags:
`{2: 37,526, 3: 1,211, 1: 1, 0: 1}`. Nodes sit at 0x80-byte strides inside
the code (e.g. 0x00C4, 0x0100, 0x0180, 0x0200, 0x0280, 0x0300, …) — they are
the seams between the 128-byte evaluation cells.

### 4.2 Load-time patching (from `mvlsim .txloadm`)

**Pass 1 — relocation:** each node word is replaced by
`(absolute_buffer_address_of_next | tag)`; the chain is followed through the
original offsets.

**Pass 2 — patch by tag** (only for type "630" / `-PREFETCH_ENABLE`):

| Tag | Written instruction | Meaning |
|----:|---------------------|---------|
| 0 | `0x7C682AA6` (`mfspr r3, 0xa8`) | anchor; address remembered as r25 |
| 1 | `0x7C682AA6` | anchor; address remembered as r22 |
| 2 | `0x48000000 + disp + 1` (`bl`) | call site; `disp = (node − r25) & ~0x3FF` |
| 3 | `0x48000000 + disp + 1` (`bl`) | call site; `disp = (node − r22) & ~0x3FF` |

**Pass 2 for our model (type "ppc", no `-PREFETCH_ENABLE`):** every node is
overwritten with **`0x60000000` (nop)** — the cell chain then executes
linearly. The nodes are the "seams" between the cells; the model contains
**no `bl` and no traps** in the whole code region.

### 4.3 Entry point

```
00000000: 48 00 00 28     b 0x28            ; entry: jump over data/glue
00000004: 00 00 00 00     (patch node, tag 0 -> nop)
00000008: 38 63 03 80     addi r3, r3, 0x380
0000000c: 7c 00 1a 2c     dcbt 0, r3        ; cache-touch helper
00000010: 4e 80 00 20     blr
00000014: 00 00 00 05     (patch node, tag 1 -> nop)
00000018: 38 63 03 80     addi r3, r3, 0x380
0000001c: 7c 00 1a 2c     dcbt 0, r3
00000020: 80 63 10 00     lwz r3, 0x1000(r3)
00000024: 4e 80 00 20     blr
00000028: 00 00 00 17     (patch node, tag 3 -> nop)
0000002c: 7d 48 02 a6     mflr r10          ; bootstrap #1 begins
```

`b 0x28` (PC-relative ⇒ target 0x28) jumps over the two patch nodes and the
dcbt helpers; after patching, 0x28 is a nop and execution falls into the
bootstrap at **0x2C**.

---

## 5. Call Convention and Per-Cycle Execution

### 5.1 Who calls the model and how (`mvlsim .txcall`, 0x10048818)

The per-cycle evaluator `lk_std` (0x10047BBC) performs, for every cycle:

1. zeroes `sim→0x998` (assert counter word) and the byte at `sim→0x9A0`
   (= call-block +0x168, state slot 0x8168) — the model's "assert budget";
2. calls `.txcall(0x10048818)` with **r3 = `sim→0x82C`** (the per-cycle
   entry = **0x1BCD60**, from header +0x80) and **r4 = `sim→0x838`**
   (the call block);
3. conditionally calls `.txcall` a second time with r3 = `sim→0x828`
   (bootstrap #3, when `sim→0x80C != 1`) or r3 = `sim→0x820`
   (bootstrap #1, when `sim→0x80C == 1` **and** `sim→0xA8C == 0`).

For **this model** `sim→0x80C = 1` and `sim→0xA8C = 1` (flags word bit 3),
so the second call is **skipped** — one evaluation per cycle, entry 0x1BCD60.

`.txcall` builds the call block (see 5.3), then, on the native path
(`sim→0x10FC != 1`, i.e. no `-VM`), treats the entry as a **function
descriptor**: it stores the entry value at `sp+0x40` and lets `_ptrgl`
(0x10009718) do

```
r0  = *(sp+0x40)   ; = entry = 0x1BCD60  -> jump target
r2  = *(sp+0x44)   ; = 0               -> "TOC" (unused by the model)
r11 = *(sp+0x48)   ; = 0               -> chain
bctr               ; jump to 0x1BCD60 with r3 = call block
```

So the model starts at 0x1BCD60 with:

| Register | Value at entry | Role |
|----------|----------------|------|
| r3 | 0 (call block base) | context / call block |
| r1 | call block + 0x7FFC | stack; `stmw r1, 0x68(r3)` frame saves r1..r31 at cb+0x68 |
| r10 | `mflr r10` → the **return address** (the interpreter uses 0xDEADBEEF as "return to caller") | saved by every prologue, restored by the epilogues |
| r13..r20 | bootstrap: r13 = cb+0x8000, +0x10000 each | **8 state bank bases** |

### 5.2 Return path (cell epilogues)

The model ends with `mtlr r10; blr` (e.g. the final one at **0x4BA83C**).
Between entry and the epilogues, r10 is clobbered by the cells, so every
epilogue restores it from the `stmw` frame:

```
addi  r1, r13, 0        ; r1 = r13 = cb+0x8000
lmw   r2, -0x7f94(r1)   ; restore r2..r31 from cb+0x6C  (r10 <- cb+0x8C = saved entry r10)
addi  r3, r1, 0
lwz   r1, -0x7f98(r3)   ; r1 <- cb+0x68 = saved entry r1
mtlr  r10
blr                    ; return (to the caller / final return at 0x4BA83C)
```

There are **5 such return sites** (`mtlr r10; blr`), including bootstrap #1's
return at 0x1BCD5C and the final model return at 0x4BA83C.

### 5.3 Call block layout (address 0 of the state memory)

| cb+off | Slot | Contents |
|-------:|-----:|----------|
| 0x00 | 0x8000 | pointer to function descriptor → entry **0x10007624** (assert printer) |
| 0x04 | 0x8004 | `sim→0x87C` (IP) |
| 0x08 | 0x8008 | pointer to descriptor → entry **0x10005C10** (`.txperf`) |
| 0x0C | 0x800C | `sim→0x64` |
| 0x10 | 0x8010 | **model base = 0** (jump-table base; set from `sim→0x818`) |
| 0x14 | 0x8014 | pointer to descriptor → entry **0x10035A2C** (`txaa_wr`) |
| 0x18 | 0x8018 | pointer to descriptor → entry **0x10033FCC** |
| 0x18C | 0x818C | pointer to descriptor → entry **0x10048958** |
| 0x40 | 0x8040 | **assert message offset** (written by the model; read by the printer) |
| 0x44 | 0x8044 | spare |
| 0x48 | 0x8048 | flag: 0 = native, 1 = VM |
| 0x4C..0x60 | 0x804C..0x8060 | copies of the +0x00/+0x14/+0x18 descriptor entries/TOCs (bootstrap) — **0x5C = 0x10007624**, the assert-printer entry; the +0x08/+0x18C descriptors are copied to 0x164/0x168 and 0x190/0x194 |
| 0x64 | 0x8064 | spare (saved-IP area) |
| 0x68..0xE4 | 0x8068..0x80E4 | `stmw`/`lmw` save frame (r1..r31) |
| 0x198 | 0x8198 | init-state list head (bootstrap #1 walk, see 5.5) |

The bootstraps copy the descriptor entries into 0x4C..0x60 etc. at every
entry; the interpreter therefore pre-fills the call block so the copies
produce the same values.

### 5.4 Jump-table dispatchers and the assert-printer calls

**Dispatchers (37 sites, `mtlr r3; blr`)** route the evaluation between cell
blocks:

```
lbz     r29, -0x526b(r15)      ; a state wire (e.g. slot 0xAD95 bit 0)
rlwimi  r24, r29, 0, 31, 31    ; -> index bit
lwz     r3, -0x7ff0(r13)       ; r3 = cb+0x10 = model base (0)
slwi    r0, rIdx, 2            ; index * 4
add     r3, r3, r0
addi    r3, r3, 0x10c8
addis   r3, r3, 0x12           ; r3 = model_base + 0x1210C8 + idx*4
mtlr    r3
blr                           ; jump into the jump table (a row of `b`s)
```

The jump table at `0x1210C8` etc. contains `b <block>` instructions; the
evaluation walks the cell space in a regular **0x4000-strided pattern**, two
interleaved passes (consistent with the L1/L2 planes), from the low cells up
to the final return at 0x4BA83C.

**Assert-printer calls (5,147 sites, `mtlr r3; blrl`)** — every single
indirect call in the model:

```
lwz r3, -0x7fa4(r13)   ; r3 = cb+0x5C = 0x10007624 (assert printer)
mtlr r3
lwz r2, -0x7fa0(r13)   ; r2 = cb+0x60 (TOC, ignored)
blrl                   ; call printer; it reads cb+0x40 (the message offset)
```

### 5.5 Bootstrap #1 (init entry, 0x2C)

Same prologue as #2, then:

```
lwz  r21, -0x7e68(r13)   ; cb+0x198 = init-state list head (0 -> skip)
loop: cmplwi r21, 0 ; beq done
      lwz  r22, 0(r21)    ; target address
      lbz  r23, 7(r21)    ; value byte
      lwz  r21, 8(r21)    ; next node
      stb  r23, 0(r22)    ; write the initial value
      b    loop
done: li   r24, 1
      stb  r24, 0x6880(r14)      ; slot 0xE880 = 1
      li   r25, 0
      stb  r25, 0x6882(r14) ...  ; slots 0xE882..0xE8FA = 0 (constants)
```

The constant writes land in the pin-slot range (0xE880+) — default wire
values that the per-cycle pin application then overrides.

### 5.6 Bootstrap #2 (per-cycle entry, 0x1BCD60)

Prologue + descriptor copies + bank setup (r13..r20), then a conditional
"memory-array write" path:

```
lbz  r25, 0x79e0(r14)          ; slot 0x79E0 flag; if 0 -> skip
lwz  r31, 0x6e00(r14)          ; array index
...  lwz r28/r24/r29/r26/r22/r21 from slots 0x644C..0x6460
addi r23, r20, 0x1aac
addis r23, r23, 0x38           ; r23 = cb + 0x3F9AAC (array table base)
slwi r31, r31, 6               ; index * 64
add  r31, r31, r23
stw  r28, -0x8000(r31) ...     ; 32-bit store into the array entry
```

Then it falls into the cells.

### 5.7 Bootstrap #3 (0x2341CC) — state-block copy

Copies `0x1E40 × 8 = 0xF200` bytes (header +0x04) from the low state region
to the upper region via `lwz`/`stw` pairs in a loop (`addi r21/r22, 8;
bne`). Not invoked per cycle for this model (§5.1); used by other model
configurations to update latch planes.

---

## 6. Instruction Set Actually Used

Whole-region histogram (words that decode; 0x60000000 nops excluded):

| Mnemonic | Count | Mnemonic | Count | Mnemonic | Count |
|---------:|------:|---------:|------:|---------:|------:|
| lbz | 255,340 | addi | 10,163 | add | 3,304 |
| and | 163,666 | xor | 9,955 | orc | 3,289 |
| or | 146,004 | li | 9,666 | xori | 2,751 |
| andc | 83,635 | lis | 9,551 | addis | 2,664 |
| stb | 61,154 | beq | 7,582 | mulli | 2,624 |
| lwz | 52,033 | bne | 6,664 | sth | 2,428 |
| stw | 34,007 | ori | 5,444 | b | 1,756 |
| nor | 23,011 | mtlr | 5,189 | lha | 1,026 |
| cmplwi | 14,246 | blrl | 5,147 | slwi | 774 |
| rlwimi | 14,092 | nand | 4,724 | srwi | 639 |
| lhz | 120 | clrlwi | 3,356 | rlwinm | 506 |
| eqv | 308 | blr | 42 | subfc | 10 |
| lmw | 5 | mflr | 2 | stmw | 2 |

Notes:
- **No** `stbu/lbzu/lwzu/stwu/lhzu/sthu`, no `bcctr/bclr/bdnz`, no `cmpw/`
  `cmpwi` (only `cmplw/cmplwi`), no dot-forms, no `oris/xoris` in the code
  region proper.
- `blr`/`blrl` are **opcode 19** (`0x4E800020`/`0x4E800021`), not op31.
- 42 `blr` = 37 jump-table dispatches + 5 return sites (§5.2/5.4).
- 5,147 `blrl` = all assert-printer calls (§5.4).

---

## 7. Symbol Table

### 7.1 Record formats

**Class A (`0x70050000`)** — 8,515 records:

```
word0(4)  word1(4)  keep(1)  name(N)\0
```

| Field | Example | Meaning |
|-------|---------|---------|
| word0 | `70 05 00 00` | class |
| word1 | `04 04 08 d4` | `0x0404` + **slot** = `0x08D4` |
| keep | `00` | name prefix to keep (see 7.2) |
| name | `"GKO.BA0.BAAA.NAN0.L1"` | compressed name |

**Class B (`0x02040000`)** — 9,487 records:

```
word0(4)  word1(4)  b8(1)  keep(1)  name(N)\0
```

slot = `(b8 << 8) | (word1 & 0xFF)`.

**Slot → state address:** the *slot* is the offset within any state bank;
the bank is selected by the base register used in the code
(`off >= 0 → slot = off`, `off < 0 → slot = off + 0x10000`). One logical
signal may be read/written from several banks (planes L1/L2). Slots
0x8000..0xFFFF (incl. the pin slots 0xE800..0xEB00) are always reached via
**negative** displacements (`disp = slot − 0x10000`).

The region beyond the header-declared symbol size (0x510FAC..0x5155EF)
holds more class-B records — LSSD / shift-chain register names such as
`"U.ABCD.L2"`, `"…CA.BIT0.L1"` (they were not part of the name count).

### 7.2 Name compression

`full_name = previous_full_name[:keep] + name`; `keep == 0` means the name is
already complete. Example (from the file):

```
004ba840: 70 05 00 00 04 04 08 d4 00 00 00 47 4b 4f 2e 42 41 30 2e 42 41 41 41 2e 4e 41 4e 30 2e 4c 31 00
           |--w0--|  |--w1--|  |k|  "GKO.BA0.BAAA.NAN0.L1\0"          (keep=0, full name)
004ba860: 70 05 00 00 04 04 08 fc 00 00 13 32 00
           "2"   keep=0x13=19  => prev[:19]+"2" = "GKO.BA0.BAAA.NAN0.L2"
004ba86d: 70 05 00 00 04 04 08 c8 00 00 10 31 2e 4c 31 00
           "1.L1" keep=0x10=16 => prev[:16]+"1.L1" = "GKO.BA0.BAAA.NAN1.L1"
```

Names resolve to signals such as `GKO.BA0.BAAA.NAN0.L1` (a bit of a NAN bus,
L1 phase), `GKO.FE0.FEWE.NAN1.L1`, `GKO.JTC.SMPLD.L2`,
`GKO.IC0.ICAA.FWD_LAT.L2.RAM_0_HOLDL2`, `GKO.CCC.IDN1.BIT3.L2`, … (chip
hierarchy: FE0 execution unit, JTC JTAG, IC0/DC0 caches, CCC completion
control, CBB, LA0/LAS L2 addressing, BAC bus arbitration, …).

16,862 unique slots have names; the code touches 61,928 unique slots.

---

## 8. Assert Mechanism (how the model reports asserts)

There is **no separate "assert table"** in the file: the region formerly
described as one (0x5155EF) is the **pin table** (§9). Asserts work entirely
through the call block:

1. Every assert cell tests a condition wire:

```
lbz     rX, <flag>(r14)        ; condition wire
cmplwi  rX, 1
bne     skip
li      rY, <offset>           ; e.g. 0x59
stw     rY, -0x7fc0(r13)       ; slot 0x8040 = cb+0x40 = MESSAGE OFFSET
skip:
```

2. The next assert-printer call (`blrl` through slot 0x805C, §5.4) reads
   `cb+0x40` and prints. The calls are pipelined: each printer call emits the
   offset written by the previous cell; the last offset of a cycle is emitted
   at the start of the next cycle. Offset 0 = nothing.

3. MVLSIM's printer (0x10007624) parses the decimal severity from
   `sim→0x868 + cb+0x40` (messages base + offset), enforces `-maxasserts`
   (3 in `COSIM.sim`), increments `sim→0x99C` (the "Assertions triggered"
   counter) and logs the line through the sprintf engine (0x10007840) using
   the format `"%d:%s>  %s"` (0x62D34), e.g.

```
29 ASSERT   | 8:GKO.CCC:ccc.dsl:5856>  cb0 illegally marked finished
```

   (The `8:`/`9:` prefix is an mvlsim printer index; the interpreter prints
   `<sev> | <path> >  <text>` instead.)

Verified offsets: message 0 at offset 0x00 ("completion buffer 2 finished
both…"), message 1 at **0x59** ("completion buffer 2 TYPE not valid") — which
matches the `li rY, 0x59` constant in the assert cells.

---

## 9. Pin Table (chip I/O contract) — full encoding

Located at **0x5155EF .. 0x515FA6**, right after the symbol records and
before the message region. Order equals `model/pin.list` order.

### 9.1 Group structure

Each pin is a group:

```
70 22 00 00 NN   group header (NN = bit count of the pin)
<slot records>   one or more per bit (see 9.2)
<name record>    see 9.3
```

### 9.2 Slot records

| Pattern | Length | Meaning |
|---------|-------:|---------|
| `02 01 eY ZZ 00` | 5 | slot 0xE Y ZZ (first record of a bus pin) |
| `01 01 eY ZZ 00` | 5 | slot 0xE Y ZZ |
| `0f 02 01 eY ZZ 00` | 6 | slot 0xE Y ZZ |
| `0f 01 01 eY ZZ 00` | 6 | slot 0xE Y ZZ |
| `0e 01 01 eY ZZ 00` | 6 | slot 0xE Y ZZ |
| `12 02 01 eY ZZ 00` | 6 | slot 0xE Y ZZ |
| `0c 02 01 eY ZZ 00` | 6 | slot 0xE Y ZZ |
| `03 00 00 00 00 00 00 01 eY ZZ` | 10 | LSSD pin slot (e.g. `e8 0b` = 0xE80B) |

Every slot is in the **0xE800..0xEB00** range. A pin's bits map to the slot
list **in pairs** (2 slots per bit — the L1/L2 planes): e.g. `PIN_A` bit 0 =
slots `0xEA15, 0xE95E`, bit 1 = `0xEA17, 0xE88F`, … `DH` bit 0 = `0xEAB7,
0xE91B`, … The first 5-byte `02 01 …` record is bit 0's first slot.

### 9.3 Name records

| Pattern | Meaning |
|---------|---------|
| `0f 00 <name>\0` | full name, NUL-terminated (e.g. `PIN_A`) |
| `01 <len> <name>\0` | length-prefixed name (e.g. `01 05 "ACK_"`) |
| `0e/12/0c <b1> <name>\0` | NUL-terminated name (e.g. `0e 04 "CHECKSTOP_"`, `12 05 "LK_OUT"`) |
| `04/05 <name>\0` | LSSD pin name, NUL-terminated (e.g. `"L1_TSTCLK"`, `"RST_"`) |

Names are **prefix-compressed** against the previous pin (a stored name is a
suffix of the real name):

| Stored | Real | Stored | Real |
|--------|------|--------|------|
| `PIN_A` | PIN_A | `H` | DH |
| `ACK_` | AACK_ | `L` | DL |
| `P` | AP | `P` | DP |
| `RTRY_` | ARTRY_ | `RTRY_` | DRTRY_ |
| `BG_` | BG_ | `REQ_` | QREQ_ |
| `R_` | BR_ | `YSCLK` | SYSCLK |
| `VSEL` | BVSEL | `BST_` | TBST_ |
| `CHECKSTOP_` | CHECKSTOP_ | `O` | TDO |
| `I_` | CI_ | `EA_` | TEA_ |
| `KSTP_` | CKSTP_ | `LBISYNC_` | TLBISYNC_ |
| `LK_OUT` | CLK_OUT | `MS` | TMS |
| `DBG_` | DBG_ | `RST_` | TRST_ |

The 41 pins (in table order, == pin.list): `PIN_A(0:31)`, `AACK_`, `AP(0:3)`,
`ARTRY_`, `BG_`, `BR_`, `BVSEL`, `CHECKSTOP_`, `CI_`, `CKSTP_`, `CLK_OUT`,
`DBG_`, `DH(0:31)`, `DL(0:31)`, `DP(0:7)`, `DRTRY_`, `GBL_`, `HRESET_`,
`INT_`, `L1_TSTCLK`, `L2_TSTCLK`, `LSSD_MODE_`, `MCP_`, `PLL_CFG(0:3)`,
`QACK_`, `QREQ_`, `SRESET_`, `SYSCLK`, `TA_`, `TBST_`, `TCK`, `TDI`, `TDO`,
`TEA_`, `TLBISYNC_`, `TMS`, `TRST_`, `TSIZ(0:2)`, `TS_`, `TT(0:4)`, `WT_`.

The code reaches the pin slots mostly through **bank 2 (r15)** with negative
displacements (`disp = slot − 0x10000`, e.g. slot 0xE95E → `-0x1692(r15)`):
~3,709 of ~4,015 pin-range accesses use r15, the rest r13 (193) and r20
(113). Input pins are written into all 8 banks before the cycle; outputs are
read from bank 2 afterwards.

---

## 10. Message String Region (0x515FB6, 402,621 bytes)

NUL-terminated ASCII strings: **message records** and **DSL paths**.

A message record is `"<sev>,<text>\0"` followed by **one or more** path
strings `"GKO.<block>:<file>.dsl:<line>\0"`:

```
00515fb6: 32 39 2c 63 6f 6d 70 6c 65 74 69 6f 6e 20 62 75  |29,completion bu|
00515fc6: 66 66 65 72 20 32 20 66 69 6e 69 73 68 65 64 20  |ffer 2 finished |
...
"29,completion buffer 2 finished both with and without fp exception\0"
"GKO.CCC:ccc.dsl:5643\0"
```

A direct byte scan finds **214** `"29,"`-prefixed records and ~9,243 `"GKO."`
path occurrences (the earlier parsed listing reported 228 messages / 7,195
paths — the exact count depends on the parsing rule, since several messages
share paths and some paths repeat). The model refers to messages by the
**byte offset** of the `"29,…"` record (§8), so the offset is the canonical
key, not the index.

The loader can translate this region from EBCDIC to ASCII at load time for
EBCDIC-built models (selected by the header magic at 0x24 and `sim→0x10fc`).

---

## 11. Value / Plane Model

- Two-value logic (0/1), one byte per wire slot.
- 8 state banks (r13..r20) are copies/planes; the same slot can be read in
  one plane and written in another (L1/L2 latch phases). The header stride
  count (0x6C = 2) matches the two phases.
- Slot addressing: `slot = disp` for `disp ≥ 0`, `slot = disp + 0x10000` for
  `disp < 0`. Address = bank base + disp. The pin slots live at 0xE800..
  0xEB00 (reached via negative displacements).
- For Verilog conversion, planes collapse into a single variable per slot.

---

## 12. Decoding Worked Examples

### 12.1 A combinational cell (SOP)

Raw bytes at 0x40B6AC:

```
0040b6ac: 8b 0e 6d b5   lbz r24, 0x6db5(r14)    ; load wire  (slot 0x6DB5)
0040b6b0: 7f 1a d0 78   andc r26, r24, r26
0040b6b4: 8b 0e 6e 82   lbz r24, 0x6e82(r14)
0040b6b8: 8b ae 6d af   lbz r29, 0x6daf(r14)
0040b6bc: 9b 8e 6e 8d   stb r28, 0x6e8d(r14)    ; store wire
0040b6c0: 7f bc c0 78   andc r28, r29, r24
0040b6c4: 7f 5a e3 78   or  r26, r26, r28
...
0040b6f0: 9b 8e 6e bc   stb r26, 0x6ebc(r14)    ; store wire -> slot 0x6EBC
```

Decoded pseudocode (names from the symbol table; planes collapsed):

```
w[1][0x6e8d] <= r28;                                    // block input
w[1][0x6ebc] <= (~(((w[1][0x6db5] & ~r26)
                  | (w[1][0x6daf] & ~w[1][0x6e82]))
                  | (w[1][0x6db9] & ~w[1][0x6e8d]))
                  | w[1][0x6dbe])
              & (w[1][0x6dbf] | w[2][-0x7fdd]);
              // slot 0x6EBC = GKO.HI0.HIRA.NAN2.L2
```

This is a sum-of-products logic cone: `out = ~(set-terms) & (reset-terms)`.

### 12.2 Latch / hold pattern

```
w[1][0x6e41] <= (((w[1][0x6d8d] & w[1][0x6e41] & ~GKO.FE0.FEWE.NAN1.L1)
                | (w[1][0x6e41] & GKO.FE0.FEWE.NAN1.L1)) ...)
```

i.e. `Q <= (D & Q & ~hold) | (Q & hold)` — a transparent latch with a
hold/phase chain (L1/L2).

### 12.3 Bit packing (`rlwimi`)

`rlwimi r23, r28, 0x1e, 1, 1` — with `SH = 31 − b` moves wire bit 0 into
vector bit `b`; a chain of 32 such instructions assembles a request vector:

```
{31:w[2][-0x7fd4], 30:w[2][-0x7fd5], ..., 0:w[2][-0x7fff]}
```

### 12.4 Priority decoder (`if / else-if` chain)

```
if (vector == 0x80000000) { mem32[2][-0x79dc] <= 0; mem32[2][-0x79d8] <= 0; }
else if (vector == 0x40000000) { ... } else if (vector == 0x20000000) { ... }
...
```

Each case stores 32-bit constants (instruction fields / immediates) and sets
control wires such as `w[2][-0x7fff] <= 1` (a pending flag).

### 12.5 Assert cell (see §8)

```
lbz     r26, 0x6f7e(r14)     ; condition wire (slot 0xEF7E)
cmplwi  r26, 1
bne     0x1f1dc0
li      r23, 0x59            ; message offset 0x59 = "completion buffer 2 TYPE not valid"
stw     r23, -0x7fc0(r13)    ; slot 0x8040 = cb+0x40
```

### 12.6 Dispatch site (see §5.4)

```
lbz     r29, -0x526b(r15)    ; slot 0xAD95
rlwimi  r24, r29, 0, 31, 31  ; index bit
lwz     r3, -0x7ff0(r13)     ; model base (slot 0x8010)
slwi    r0, r24, 2
add     r3, r3, r0
addi    r3, r3, 0x10c8
addis   r3, r3, 0x12         ; 0x1210C8 + idx*4
mtlr    r3
blr
```

---

## 13. Interpreter Verification (`cosim.py`)

The interpreter `cosim.py` (in the repository root) implements everything
above and reproduces the model's behaviour:

- one-time init pass (entry 0x2C): **done, 405,910 instructions**;
- per cycle (entry 0x1BCD60 → final `blr` at 0x4BA83C): **done in ~30–40k
  instructions** (first cycle with the demo inputs: 30,647);
- the model reacts to the bus: asserting `TS_` (transfer start) with an
  address on `A` makes the model drive `AACK_ = 0` (transfer acknowledged);
  it also drives `BVSEL`, `PLL_CFG`, `TSIZ`, `TT` from its internal state;
- the pin slots 0xE8xx..0xEAxx, the assert offsets (0x59 → message 1) and
  the call-block convention all match the analysis above.
