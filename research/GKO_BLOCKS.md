# GKO Top-Level Logic Blocks — analysis from the compiled model

**Source:** symbol table of `model/COSIM.m2630opt.Jul1599` (16,865 named
signals, 85 top-level `GKO.<BLOCK>` names) + `cosim.py` interpreter runs.
**Document version:** 1.0

> GKO = **Gekko**, the GameCube CPU: an MPC750-class (PowerPC G3) core with a
> paired-single FPU, an on-chip L2, a DMA engine, thermal management and an
> ECID — all confirmed by signal names in the model (`PAIRED`, `L2CR`,
> `DMA_Q*`, `THM_*`, `ECID*`).
>
> Naming is the IBM-internal DSL block naming. Signal-name suffixes:
> `NAN/NBN/PCN/PDN/PBN` = logic cones (NAND-style networks), `CR.L1/L2` =
> latch phases, `.BITn.L1/L2` = vector bit + phase, `.ABCD.L2` = 4-bit slice.

---

## 1. Block inventory (85 blocks, top 45 with role)

| Block | Signals | Role (evidence from signal names) |
|------:|--------:|----------------------------------|
| L20 | 2339 | **L2 cache** — `L2DCACHEH/L2DCACHEL` (L2 data array, high/low halves), `L2FS_REG` (L2 function-specific registers), `L2DA/L2DB` |
| LAS | 825 | **Load/store unit (LSU) datapath** — `FSQ_*` (FP store queue), `FDQ/HDQ/CDQ_PQA`, `LGPR` (GPR port), `LQU_QU_*`, `FSQ_TAG`, `FSQ_BYTE_REV`, `EIEIO_SYNC` |
| CCC | 724 | **Completion + register renaming** — `RNBUFF0..6` (156 rename buffers), `CRFIELD*` (96, CR renaming), `VALIDNONSPEC`, `FREEZE_LATCH`, `IDN*` (instruction IDs), `CBB_UBR` |
| JTC | 616 | **JTAG / LSSD / clock control** — `GCLK_*`, `THCLK_*`, `LSSD_SCAN*`, `DIAGLAT*`, `RUNNCOUNTER`, `SNPLAT`, `STOP_*` |
| BP0 | 519 | **Bus driver / array (BP0)** — `BBFM/BBGB/BBBG/BBGC/BBFO/BBGD/BBBD/BBGE` slices (L2/L4) — not fully identified |
| DM0 | 490 | **DMA engine queues** — `DMA_Q0..Q7` (8 queue entries), `DMA_Q*_MA` (memory address), `DMA_Q*_CA` (cache address), `DMA_Q*_CNT` |
| LLC | 441 | **D-cache access / LSU–FXU arbitration** — `LLC_FXU_SEL_*` (FXU select), `ST_MISS_LAT`, `LLC_FINISH_HIT_RAW`, `HIT_REN_EN`, `FX_DTAG`, `LAC_MULTS_GPR`, `MUNGE_ROT` |
| CB0 | 388 | **Completion buffer 0** — `CB0_BR0_ADDR_HI` (branch-0 address), `BR0_INSTR` (instruction), `CBAL..CBAF` slices, `CBD*` (data) |
| CBB | 376 | **Branch predictor (BHT + BTIC)** — `CBB_BHT_WR0/1_DATA` (158 BHT signals), `BHT_LINE0/1`, `PADDR0/1` (predicted address), `VALID` |
| DLS | 354 | **D-cache operation/state control** — `REQ_LAT`, `QUEUED_REQ_LAT`, `LSM/LDM` (load/store miss), `DCBZ/DCBST/DCBZ_INST` (cache ops), `LD_REQ`, `DCOP_STM` |
| CS0 | 327 | **Cache-line state arrays** — `CSPMRGA..I` (18 each), `CSR*` (cache state registers) |
| CDC | 320 | **Chip/power/clock control** — `DOZE_LATCH` (power state), `PFM_LAT` (performance monitor), `REGOP_*`, `FWB0` |
| BAC | 312 | **Bus address control (BIU address tenure)** — `AT_LAT*` (address tenure), `SNPI_LAT` (snoop invalidate), `RETRY_LAT`, `KILL_LAT`, `L2CST*_LAT` (L2 cache state), `APAR_LAT` (address parity) |
| BDR | 298 | **Bus data return (data-in path)** — `RLD_LAT*` (reload data), `RUNQ_LAT*` (run queues), `RMSM_LAT`, `XGNT_LAT`, `STKY_FAIL` |
| FIC | 294 | **Instruction fetch** — `FIR0..9` (fetch instruction regs), `FIMV` (fetch invalid), `FIB4` |
| IC0 | 288 | **I-cache array 0** — `ICAA` (266): `WL0..3_EN_LAT` (word lines), `READ_LAT`, `FWD_LAT`, `SWAP` |
| DC0 | 286 | **D-cache array 0** — `DCAA` (260): `CSE_LAT` (cache-set enable), `RRAM_0_HOLDL2` (redundancy RAM) |
| BD0 | 271 | **Bus data driver slices** — `BDAA..BDCB`, `BDLC` |
| DL0 | 267 | **Bus data latch slices** — `DLAB..DLEB` |
| GE0 | 260 | **Global/SPR + counters** — `HID_G_REG` (HID register), `QNTR0..7` (queue counters), `DMAU` (DMA upper), `WPAR` |
| LE0 | 248 | **Load-execution datapath slices** — `LEAA..LEAL`, `LEID/LEIB/LEAH/LEAK` |
| LA0 | 244 | **Load-address generation** — `LAAN` (63, address adder network), `LABP`, `LABC`, `LAAE`, `LAXY`, `LNNN` |
| BA0 | 240 | **Bus-address register slices** — `BAAA..BACB` |
| QSR | 234 | **Status/queue registers** — `TSCA..TSCV` (24 each), `TSXX`, `FLIP_LAT*` — function not fully identified |
| FA0 | 233 | **FPU adder/array slices** — `FACA`, `FAAI`, `FAAC/FAAB/FAAD/FAAF` |
| MM0 | 224 | **MMU arrays** — `DMXV/DMXM/DMXB/DMXC` (data MMU translation), `BIST_ADDR`, `MAAB` |
| DQC | 223 | **D-cache data-queue control** — `DQ3_REQ_STATE`, `ST_BEN_*` (store byte enables), `ST_MERGE`, `WR_LF`, `ZDVAL`, `SNOOP_RETRY`, `LOAD_DWL`, `HIT_B29` |
| CSC | 220 | **System timers / thermal** — `TB_STATE0/1`, `TB_CARRY` (time base), `DEC0` (decrementer), `THRLAT`, `TENC`, `CATG/CBTG/CTTG`, `TQUAL_LAT`, `THM_*` |
| HIC | 220 | **HI control / HID registers** — `HID0`, `HID1`, `HIC_ESPWE`, `HIC_SPARE0_REG_0` |
| CB1 | 218 | **Completion buffer 1** — `CBDJ`, `CBD_REGEN`, `CBLFF`, `STARL2_*` |
| BDT | 216 | **Bus data transfer (data-out timing)** — `ALAT*`, `OE_LAT*` (output enable), `LAT*`, `ARTRY` (8) |
| ICC | 212 | **I-cache controller** — `WAY_SEL_LAT` (way select), `VALID3_L1/L2`, `ICC_CSE`, `WORD_INDEX_CNTR`, `LIBAT_WIMG` (I-BAT + WIMG), `ICM_STM`, `IPWR_MAN` |
| HA0 | 210 | **Array slices (HA0)** — `HAAA..HAAG` — replicated slice structure, not fully identified |
| FWN | 209 | **FPU write-back network** — `FWNK/FWNL/FWNO` (result network output) |
| DQ0 | 194 | **D-cache data queue 0 (store pipe)** — `ST_PIPE_SHIFT_REG`, `DQAA..DQXF`, `Q0_DW0..3` (data words) |
| DMM | 186 | **Data MMU** — `L1_TLB_HIT`, `LBAT_HIT/LBAT_IG/LBAT_G` (BAT), `L1_DM0_LRU`, `DMM_REQ_CACHE`, `LEXCEP_EN`, `BIST_ALG` |
| BTC | 162 | **L2 / bus transfer control** — `L2CR_LAT` (L2 control register), `L2DHIT`, `L2DBSY`, `L2SNP_OVERRIDEN`, `ILD_REQ/ILD_RLD` (instruction load) |
| CB3 | 162 | **Completion buffer 3** — `CBQB..CBXH` slices |
| DAE | 160 | **Data address translation** — `ST_RID/LD_RID` (real-address IDs), `SIZE_WIM` (WIMG), `MISS_CSE`, `ADDR_0/1_CSE`, `IBIT_HOLD`, `BCNT_CB` |
| LS0 | 159 | **LSU queues + FPR file** — `LS0_FDQ/LS0_CDQ/LS0_HDQ` (queues), `FPR_REG` (FPR register file), `HPR_REG`, `LS0_*_TAG` |
| WA0 | 157 | **Special registers / ECID** — `ECIDREG1/2` (71 ECID signals), `SP_FUSEREG1/2`, `WAITRREG1/2` |

## 2. Remaining blocks (small arrays, not fully identified)

| Block | Sig | Block | Sig | Block | Sig |
|------:|----:|------:|----:|------:|----:|
| XEA | 156 | XEB | 132 | DA0 | 139 |
| XE2 | 31 | XF0 | 5 | JAB | 118 |
| TWC | 117 | XM0 | 114 | FW0 | 112 |
| FI0 | 108 | HW0 | 107 | FDC | 106 |
| FI1 | 103 | TM0 | 79 | LL0 | 73 |
| HI1 | 71 | HI0 | 65 | XD0 | 63 |
| IQ0 | 59 | FE0 | 58 | HWC | 58 |
| LQ0 | 55 | IT0 | 54 | BT0 | 54 |
| FWC | 54 | HE0 | 53 | XXA | 43 |
| LEC | 38 | CR0 | 34 | CS1 | 34 |
| XE0 | 28 | IA0 | 28 | DMC | 28 |
| TMC | 29 | LQU | 26 | FDL | 18 |
| JAC | 18 | HDL | 18 | QAB | 11 |
| XXB | 11 | LFN | 10 | FW2 | 8 |
| HW2 | 6 | XF0 | 5 | PL0 | 4 |

Notable: `IQ0` = instruction-queue array (`IQWE` write enable, `IQCE` chip
enable, `IQCA..IQCD`); `IT0` = I-TLB tag array (`IXICBI`, `ISWRITE`,
`IUPDATE_LRU`, `ITAGWRITE`, `IUPDATE_STAT`, `XBIST_READ`); `JAB` = BIST
controller (`BISTMAP_COMP/FAILS/L2COMP`); `JAC` = PLL (`REQPLL_F/S/FD`,
`GCLK_USE_PLL`, `STATE_LAT`); `PL0` = PLL clock tree (`CLK1..3`,
`CYCLE_MODE`); `CR0` = condition-register file (`CRCR/CRXR/CRXA`); `TMC` =
thermal/timer (`THM_STM`, `SPR3_RD`, `SPR2_TIV`, `INT_HOLD`, `SYNC1`);
`DMC` = DMA queue control (`DMA_Q_STATE`, `DMAQOV`, `DMC_QCNT`); `LEC` =
LSU exception/load-execution (`LEAF/LEAX/LEXE`, `FRZLATCH`, `LIDL`);
`XF0` = FPU control (`XFTC`, `XFZB`); `LQU` = load-queue unit (`LQUB`,
`LQU_16EA`, `PAIRED_3C`).

## 3. Functional grouping

```
L2 cache       L20, BTC
I-cache        IC0 (array), ICC (control), FIC (fetch), IT0 (I-TLB)
D-cache        DC0 (array), DLS (ops/state), LLC (access arb), DQC/DQ0
               (data queues), CS0/CS1 (line state)
MMU            MM0, DMM (data TLB/BAT), DAE (data translation), IT0 (I-TLB)
Integer pipe   XEA, XEB, XE2, XF0, GE0
FPU            FE0 (execute), FW0/FWN/FWC (write-back), FDC/FDL/FI0/FI1
               (decode/latches), FA0 (adder slices) — paired-single capable
LSU            LAS, LS0 (queues + FPR file), LA0 (address), LE0/LL0/LQU/LEC
Branch         CBB (BHT+BTIC), FIC (fetch), CB0_BR0* (branch-0 in CB)
Completion     CCC (rename buffers + CR rename), CB0..CB3 (completion
               buffers), CR0 (CR file)
Bus (60x)      BAC (address tenure), BDR (data return), BDT (data transfer),
               BD0/DL0 (data drivers/latches), BP0, BA0
L2/bus ctrl    BTC (L2CR, L2 snoop)
DMA            DM0 (queues), DMC (control), GE0 (DMAU)
JTAG/test      JTC (JTAG+LSSD+clocks), JAB (BIST), JAC/PL0 (PLL)
System         GE0 (HID, counters), WA0 (ECID, SPRs), CSC (time base +
               decrementer + thermal), TMC (thermal/timer), CDC (power:
               DOZE/NAP, perf monitor), QSR (status/queues)
Arrays (unid)  XM0, TM0, BT0, IA0, XXA/XXB, LFN, HDL, QAB, FW2, HW2 ...
```

## 4. How to explore further

- `model/COSIM_m2630opt.Jul1599.names.txt` — all named signals per block.
- `cosim.py --verbose --verbose-max N` — see which named slots each cell
  loads/stores during a cycle (block-level traffic).
- `python3 decompile_model.py 0x<start> 0x<end>` — pseudocode of a cell
  region; `-d sim.dump` (cosim.py) — the full per-cycle state.
