# Gekko Paired-Single — Register File Storage and Memory Load/Store

**Subject:** how the Gekko paired-single (PS) floating-point extension stores
its two 32-bit values in the FPR register file and how they are saved to /
loaded from memory.
**Sources:** IBM Gekko RISC Microprocessor User Manual (Version 1.2, 5/25/00 —
the "Paired Single" extension sections: 2.2.3, Table 2-6/2-16/2-17, 2.3.4.3.5,
Chapter 12 psq_l/psq_st), and the compiled model `model/COSIM.m2630opt.Jul1599`.
**Document version:** 1.0

---

## 1. Executive summary

1. Each **FPR is 64 bits**. A paired-single operand is two 32-bit
   single-precision values packed into one FPR:
   * **ps0 = the high-order word (bits 0–31)**,
   * **ps1 = the low-order word (bits 32–63)**.
   (Confirmed by the manual prose and by the instruction names:
   `ps_merge00` is "MERGE high" and merges the *ps0* operands; `ps_sum0` is
   "SUM high".)
2. Loads/stores:
   * `lfs[u][x]` — load one single into **ps0** and **replicate it into ps1**.
   * `stfs[u][x]` — store **ps0 only**.
   * `lfd[u][x]`/`stfd[u][x]` — full 64-bit double load/store (format must
     match the FPR's contents; mixing double and PS is a programming error).
   * `psq_l/psq_lu/psq_lx/psq_lux` — quantized load of a **pair** (or one
     element with `W=1`), converted per the selected **GQR**; the first
     memory word goes to **ps0**, the second to **ps1**.
   * `psq_st/psq_stu/psq_stx/psq_stux` — quantized store of ps0 (and ps1 if
     `W=0`); **ps0 → memory[EA], ps1 → memory[EA+4]** (big-endian, float
     type).
3. The PS feature is gated by **HID2[PSE]**; the non-indexed quantized forms
   additionally require **HID2[LSQE]**.
4. In the compiled model, the GQR scale/type fields live in the **LLC**
   block (`LSCALE/LTYPE/SSCALE/STYPE`, duplicated as `_M`/`_H` lanes); the
   FPR data path is: load `D-cache → LL0 → FPR rename → FPR file`, FPU
   results `FE0 → FWN → FW0 → FPR file`, store read `FPR → FPR_SEL →
   FSQ/CSQ store queues`. PS/quantized control flags (`PAIRED`, `GRAPH`)
   are spread over LLC/LAS/LEC/LQU/DAE.

---

## 2. FPR register file format (Section 2.2.3, page 2-29)

> Paired single operands are represented in the 64-bit floating-point
> registers as two 32-bit single-precision floating-point values. We will
> refer to the single-precision floating-point value in the **high order
> word as ps0**, and that in the **low order word as ps1**.

```
 FPR (64 bits)
┌──────────────────────────────┬──────────────────────────────┐
│ bits 0–31   = ps0  (HIGH)    │ bits 32–63 = ps1  (LOW)      │
└──────────────────────────────┴──────────────────────────────┘
```

Both halves are processed **in parallel** by the FPU (`ps_madd` etc. apply
the same operation to ps0 and ps1). When `HID2[PSE] = 1`, the ordinary
single-precision instructions (`fadds`, `fsubs`, …) operate on **ps0** and
duplicate the result into **ps1**; double-precision instructions still
operate on the full 64-bit register. The relationship between the internal
PS format and the double format is **unspecified** — applying a double
instruction to a PS operand (or vice versa) is a programming error.

---

## 3. Loads and stores to memory

### 3.1 Enables (Table 2-6, HID2)

| HID2 bit | Name | Function |
|----------|------|----------|
| 0 | LSQE | Load/Store quantized enable for non-indexed format instructions (`psq_l`, `psq_lu`, `psq_st`, `psq_stu`) |
| 1 | WPE | Write pipe enable (write-gather pipe) |
| 2 | PSE | **Paired single enable** — 0: all paired-single instructions are illegal; 1: they can be used |
| 3 | LCE | Locked cache enable (D-cache partition / DMA) |

### 3.2 Single and double loads/stores

**`lfs` (page 12-98):**

```
if HID2[PSE] = 0 then frD <- DOUBLE(MEM(EA,4))
else frD(ps0) <- Single(MEM(EA,4)); frD(ps1) <- Single(MEM(EA,4))
```

The word at EA is interpreted as a single; in PS mode it is placed into
**ps0 and replicated into ps1**.

**`stfs`:** stores the **ps0** value only.

**`lfd`/`stfd`:** full 64-bit double load/store — use the whole register.
Because the PS and double interpretations of the same 64 bits differ,
software must keep the formats consistent (see the save/restore sequence
below).

### 3.3 Quantized paired loads/stores (`psq_l`, `psq_st`, …)

The Gekko graphics extension adds eight quantized instructions. Each uses
one of the eight **Graphics Quantization Registers (GQR0–GQR7, SPR
912–919)** selected by the 3-bit `I` field:

| GQR bits | Name | Meaning |
|----------|------|---------|
| 2–7 | LD_SCALE | scale used by a load |
| 13–15 | LD_TYPE | type of the operand in memory (load) |
| 18–23 | ST_SCALE | scale used by a store |
| 29–31 | ST_TYPE | type produced by a store |

| LD/ST_TYPE code | Type |
|-----------------|------|
| 0 | single-precision float (no conversion) |
| 4 | unsigned 8-bit integer |
| 5 | unsigned 16-bit integer |
| 6 | signed 8-bit integer |
| 7 | signed 16-bit integer |

**`psq_l frD, d(rA), W, I` (page 12-157):**

```
if HID2[PSE]=0 | HID2[LSQE]=0 then illegal
EA <- (rA|0) + EXTS(d)
lt <- GQR[I][LD_TYPE]; ls <- GQR[I][LD_SCALE]
c <- 4 ; if lt=(4|6) then c <- 1 ; if lt=(5|7) then c <- 2   ; element width
if W=0 then
    frD(ps0) <- dequantized(MEM(EA,c),   lt,ls)
    frD(ps1) <- dequantized(MEM(EA+c,c), lt,ls)
else
    frD(ps0) <- dequantized(MEM(EA,c),   lt,ls)
    frD(ps1) <- 1.0
```

* `W=0` — load a **pair**: the first element (EA) goes to **ps0**, the
  second (EA+c) to **ps1**.
* `W=1` — load **one** element into ps0; **ps1 = 1.0**.
* For float type (LD_TYPE=0) the element width c = 4 → memory layout
  **ps0 at EA..EA+3, ps1 at EA+4..EA+7** (8 bytes, big-endian).
* **Dequantization** (integer types): read integer from the cache → convert
  to sign/magnitude per type → normalize → subtract `LD_SCALE` from the
  exponent → result `F = I × 2^(−LD_SCALE)`.

**`psq_st frS, d(rA), W, I` (page 12-161):**

```
stt <- GQR[I][ST_TYPE]; sts <- GQR[I][ST_SCALE]
if W=0 then
    MEM(EA,c)   <- quantized(frS(ps0), stt,sts)
    MEM(EA+c,c) <- quantized(frS(ps1), stt,sts)
else
    MEM(EA,c)   <- quantized(frS(ps0), stt,sts)
```

* `W=0` — store **ps0 at EA, ps1 at EA+c**; `W=1` — store **ps0 only**.
* **Quantization** (integer types): move the single from the FPR to the
  completion store queue → add `ST_SCALE` to the exponent → shift the
  mantissa → convert to two's complement → round toward zero → adjust.

### 3.4 Saving/restoring FPR state (interrupt handling, page 2-30)

Because the double and PS interpretations of an FPR differ, the manual
defines a guaranteed save/restore pair (with GQR0 = 0, i.e. no conversion):

```
save:    psq_st frX, 0(r1), 0, 0    ; store ps0+ps1 (8 bytes) at 0(r1)
         stfd   frX, 8(r1)          ; store the double (8 bytes) at 8(r1)
restore: psq_l  frX, 0(r1), 0, 0    ; reload ps0+ps1
         lfd    frX, 8(r1)          ; reload the double
```

Note (manual): restoration of a **ps1 denormal is not exact** — it is
stored as 0 and restored as 0.

---

## 4. Implementation in the compiled model

### 4.1 FPR file and the load/store data path

Signal names and slots (from the model symbol table; slots are 16-bit):

| Block | Signals | Role |
|-------|---------|------|
| `LS0` | `FPR_REG` (slots 0x91DC–0x921C L2, 0x942C–0x952C L1, 0x2492/0xF592 CR) | **FPR register file** access/control port |
| `LAS` | `FPR_SEL` (0x2B82 L2, 0xF384 L1) | FPR read select (store data path) |
| `LL0` | `LL0_FA_BUF_DATA`, `LL0_DEQ_ABUF/ABUFL`, `LL0_XREN` (0x8F9C–0x9088), `LL0_RENF_L1CLK_1..5`, `LL0_RENH_L1CLK`, `LL0_REN_L1CLK`, `LL0_TRI_CLK`/`FTRI_CLK` | **load data path into the FPR**: the aligned data buffer (`FA_BUF_DATA`), dequeue buffer, and the FPR **rename/write-enable** clocks (`XREN`/`RENF` = rename FPR) |
| `FWN` | `FWN0..FWN9`, `FWNJ..FWNP`, `FWSV/FWSW/FWSX/FWSY/FWSZ` (bit slices, e.g. FWSX bits 0–15 at 0x4064–0xE264), `FWSU/FWSE` | **FPU write-back network** (result data buses to the FPR file) |
| `FW0` | `FWAA`, `FWAB`, `FWAC`, `FWAD` (24-bit select/port slices, 0x6518–0x67BC) | **four FPR write ports** of the FPU write-back |
| `FWC` | `FWEX/FWCC/FWCW/FWCA/FWCE/FWCD/FWCG/FWSC/FWNA/FWNB/FWTT/FWTU`, `FEWX/FEWY` | **FPU write control** (write enables / result tagging) |
| `LAS` | `FSQ_*` (FP store queue: `FSQ_ADDR`, `FSQ_TAG`, `FSQ_BYTE_REV_W/H`, `FSQ_STRING`, `FSQ_FLOAT_S/D`, `FSQ_WORD/HWORD/TRIBYTE`, `FSQ_PAIRED`, `FSQ_GRAPH`), `CSQ_*`, `HSQ_*` | store queues; the FP store queue carries FPR data to memory |
| `LAS` | `FSQ_PAIRED` (0x1782 L2, 0x1F85 L1), `CSQ_PAIRED` (0x6182 L2) | paired-store tagging in the queues |
| `LEC` | `PAIRED_REQ` (0x3389/0x4189), `PAIRED_MISS` (0x3189/0x3F89) | paired load request/miss in the load-execution control |
| `LQU` | `PAIRED_3C`, `PAIRED_3CW1` (0x0D84/0x9190/0x9A90) | paired load queue state |
| `LLC` | `PAIRED_M/H` (0x978E/0x988E L1, 0xE38D/0xE78D L2), `LAC_MULTS_GPR`, `MUNGE_ROT`, `LHA_SEL_PRE` | **D-cache access controller**: paired-lane flags and the data "munge"/alignment/scale handling for quantized accesses |
| `DAE` | `LD_GRAPH`/`ST_GRAPH` (0x? / DMM `LDAE_GRAPH`) | quantized ("graphics") load/store request tagging in the data-address path |

Data flow:

```
LOAD:  D-cache data → LL0 (FA_BUF_DATA / DEQ buffer) → LL0_XREN / RENF
       (FPR rename write) → FPR file (LS0.FPR_REG)
FPU:   FE0 result → FWN buses (FWSX/FWSY/FWSZ, 16-bit slices) → FW0 write
       ports (FWAA..FWAD) → FPR file (FWC write control)
STORE: FPR file → LAS.FPR_SEL → FSQ/CSQ (FP store queue) → bus
```

### 4.2 GQR scale/type fields (quantization) — in LLC

The GQR LD/ST scale and type fields are broadcast into the D-cache access
controller **LLC**, duplicated for the two PS lanes:

| Signal | Slots (L2) | Meaning |
|--------|-----------|---------|
| `LLC.LSCALE_M/H` (6 bits each) | 0x5C8E–0x678E, 0xB08E–0xBD8E | load scale (M/H lanes) |
| `LLC.LTYPE_M/H` (3 bits each) | 0x388E–0x538E, 0xAA8E–0xAF8E | load type |
| `LLC.SSCALE_M/H` (6 bits each) | 0x298E–0x838E, 0x788E–0x838E (L1) | store scale |
| `LLC.STYPE_M/H` (3 bits each) | 0x098E–0x1D8E, 0x568F–0x758F | store type |

`_M`/`_H` are the two 32-bit lanes (ps0/ps1) of the data path; the same GQR
value is applied to both. The scale multiply/align logic appears in LLC as
`LAC_MULTS_GPR` (multiply-by-scale) and `MUNGE_ROT` (byte rotation for the
8/16-bit integer types). The quantized store flag `FSQ_GRAPH` / `CSQ_GRAPH`
tags store-queue entries; the load side is tagged `LD_GRAPH` (DAE) and
`PAIRED_*` (LEC/LQU).

### 4.3 Verification notes

The model contains **no named GQR register file** — the GQRs (SPR 912–919)
are written via the generic `mtspr` path and their fields are consumed in
LLC as the `*SCALE`/`*TYPE` signals above. The FP store queue (`FSQ`) is the
completion-store-queue stage named in the manual's quantization algorithm
("move the single from the FPR to the completion store queue").

---

## 5. Conclusions

1. **Register file:** an FPR is 64 bits; a PS operand packs two singles with
   **ps0 in the high word (bits 0–31)** and **ps1 in the low word (bits
   32–63)**.
2. **Memory format (float):** psq_st stores **ps0 at EA** and **ps1 at
   EA+4** (8 bytes, big-endian); psq_l loads them back in the same order.
   `lfs` loads into ps0 and replicates into ps1; `stfs` stores ps0 only;
   `lfd`/`stfd` handle the whole 64-bit register.
3. **Quantization** (psq_l/psq_st) is controlled by GQR0–7
   (LD_SCALE/LD_TYPE/ST_SCALE/ST_TYPE) and converts between two singles and
   8/16-bit signed/unsigned integers with scaling; float type (0) passes
   through unchanged.
4. The state must be saved/restored with the **psq_st+stfd / psq_l+lfd**
   pair to preserve both interpretations across interrupts.
5. In the model, the PS data path is realized through `LL0` (load→FPR
   rename), `FWN/FW0/FWC` (FPU write-back), `LAS.FPR_SEL→FSQ` (store), and
   the GQR fields live in `LLC` (`LSCALE/LTYPE/SSCALE/STYPE`, _M/_H lanes)
   with `PAIRED`/`GRAPH` tagging across LLC/LAS/LEC/LQU/DAE.

---

## Appendix A. Reference — specification text (from the Gekko User Manual)

Extracted from `IBM Gekko RISC Microprocessor User Manual.pdf` (Version 1.2,
5/25/00); text reconstructed from the PDF content streams.

### A.1 Paired-single operand format (page 2-29)

> Paired single operands are represented in the 64-bit floating-point
> registers as two 32-bit single-precision floating-point values. We will
> refer to the single-precision floating-point value in the high order word
> as **ps0**, and that in the low order word as **ps1**. … Most of the new
> instructions for manipulating these operands allow both values to be
> processed in parallel in the execution unit. … When in paired single mode
> (HID2[PSE] = 1), all the double-precision instructions are still valid,
> and execute as in non-paired single mode. In paired single mode, all the
> single-precision floating-point instructions (fadds, fsubs, fmuls, fdivs,
> fmadds, …) are valid, and operate on the ps0 operand … The ps1 value in
> the destination register is duplicated from the ps0 result in such an
> operation. The load floating-point single instructions (lfs[u][x]) load a
> single-precision floating-point value into the ps0 position of the FPR,
> and duplicate that value in the ps1 position. The store floating-point
> single instructions (stfs[u][x]) store the ps0 value only. The
> relationship between the internal format for paired single operands and
> that for double-precision floating-point operands is unspecified. It is a
> programming error to apply double-precision instructions to paired single
> operands and vice versa. In particular, loading an operand as a double and
> then storing it as a paired single will not yield the original value back
> in memory.

### A.2 lfs (page 12-98)

> lfs frD, d(rA) — if HID2[PSE] = 0 then frD <- DOUBLE(MEM(EA,4)) else
> frD(ps0) <- Single(MEM(EA,4)); frD(ps1) <- Single(MEM(EA,4)). The word in
> memory addressed by EA is interpreted as a floating-point single-precision
> operand. If HID2[PSE] = 1 then this word is interpreted as a
> single-precision operand and placed into frD(ps0) and replicated in
> frD(ps1).

### A.3 psq_l (page 12-157)

> psq_l frD, d(rA), W, I — Paired Single Quantized Load (x'E000 0000').
> if HID2[PSE] = 0 | HID2[LSQE] = 0 then illegal. EA = (rA|0) + EXTS(d).
> lt = GQR[I][LD_TYPE]; ls = GQR[I][LD_SCALE]; c = 4; if lt=(4|6) then c=1;
> if lt=(5|7) then c=2. If W=0: frD(ps0) = dequantized(MEM(EA,c),lt,ls);
> frD(ps1) = dequantized(MEM(EA+c,c),lt,ls). Else: frD(ps0) =
> dequantized(MEM(EA,c),lt,ls); frD(ps1) = 1.0. … if W=1 then only one
> number is accessed from memory, converted according to GQR and placed into
> PS0; PS1 is loaded with a floating-point value of 1.0.

### A.4 psq_st (page 12-161)

> psq_st frS, d(rA), W, I — Paired Single Quantized Store (x'F000 0000').
> if W=0: MEM(EA,c) = quantized(frS(ps0),stt,sts); MEM(EA+c,c) =
> quantized(frS(ps1),stt,sts). Else: MEM(EA,c) = quantized(frS(ps0),stt,sts).
> If W=1 only one floating-point number from frS(ps0) is quantized and
> stored to memory starting at the effective address.

### A.5 GQRs (Section 2.1.2.9, Table 2-16/2-17)

> GQR0–GQR7 (SPR 912–919): LD_SCALE (bits 2–7), LD_TYPE (13–15),
> ST_SCALE (18–23), ST_TYPE (29–31). Quantized data types: 0 =
> single-precision floating-point (no conversion); 4 = unsigned 8-bit;
> 5 = unsigned 16-bit; 6 = signed 8-bit; 7 = signed 16-bit.

### A.6 Dequantization/quantization algorithms (pages 2-56/2-57)

> Dequantization (psq_l): 1. read integer operand from L1 cache; 2. convert
> data to sign and magnitude according to type specified in the selected
> GQR; 3. convert magnitude to normalized mantissa and exponent; 4. subtract
> scaling factor specified in the selected GQR from the exponent; 5. load
> the converted value into the target FPR. For an integer value I in memory,
> the floating-point value F loaded into the target FPR is F = I * 2^(−S),
> where S is the two's complement value in the LD_SCALE field.
>
> Quantization (psq_st): 1. move the single-precision floating-point operand
> from the FPR to the completion store queue; 2. add the scaling factor
> specified in the selected GQR to the exponent; 3. shift mantissa and
> increment/decrement exponent until exponent is zero; 4. convert sign and
> magnitude to 2s complement representation; 5. round toward zero to get the
> type specified in the selected GQR; 6. adjust the resulting value.

### A.7 State save/restore (page 2-30)

> The following sequence of store and load instructions, executed when
> HID2[PSE] = 1, is guaranteed to restore the state of floating-point
> register frX regardless of its format. Assume GQR0 contains the value 0.
> Save each register using the instruction pair: psq_st frX,0(r1),0,0 ;
> stfd frX,8(r1). Restore each register using: psq_l frX,0(r1),0,0 ;
> lfd frX,8(r1). Note that restoration of the ps1 value of a paired single
> operand is not exact: if the ps1 value is a Denorm, it will get stored as
> the value 0, and so its restored value will also be 0.
