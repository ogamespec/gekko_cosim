# Recovered netlist split by original source module

The model's symbol table keeps the design hierarchy in the wire names
(`GKO.<BLOCK>.<signal>…`), so every recovered statement is routed to the block
whose wire it drives; when the wire is a nameless local cone the block is
taken from the code region that executed it (the compiled code is laid out
block by block).

Total: **50792 statements in 85 modules** (init pass + per-cycle pass).

| module | statements | init | per-cycle | named wires | whole-word copies |
|---|---:|---:|---:|---:|---:|
| [L20](L20.txt) | 16209 | 15523 | 686 | 2144 | 6842 |
| [IC0](IC0.txt) | 4782 | 4764 | 18 | 575 | 532 |
| [LAS](LAS.txt) | 3433 | 3241 | 192 | 748 | 569 |
| [CCC](CCC.txt) | 2279 | 2198 | 81 | 584 | 526 |
| [HA0](HA0.txt) | 2030 | 132 | 1898 | 520 | 115 |
| [MM0](MM0.txt) | 1830 | 1823 | 7 | 513 | 562 |
| [GE0](GE0.txt) | 1807 | 1605 | 202 | 505 | 929 |
| [QSR](QSR.txt) | 1569 | 1564 | 5 | 458 | 236 |
| [HE0](HE0.txt) | 1173 | 287 | 886 | 227 | 27 |
| [WA0](WA0.txt) | 1129 | 1076 | 53 | 458 | 300 |
| [XD0](XD0.txt) | 907 | 894 | 13 | 137 | 298 |
| [LA0](LA0.txt) | 791 | 739 | 52 | 315 | 292 |
| [JTC](JTC.txt) | 681 | 508 | 173 | 526 | 203 |
| [XM0](XM0.txt) | 644 | 295 | 349 | 145 | 340 |
| [BP0](BP0.txt) | 616 | 504 | 112 | 433 | 140 |
| [IT0](IT0.txt) | 541 | 540 | 1 | 93 | 108 |
| [BAC](BAC.txt) | 497 | 332 | 165 | 272 | 183 |
| [LLC](LLC.txt) | 488 | 441 | 47 | 283 | 55 |
| [LE0](LE0.txt) | 449 | 344 | 105 | 301 | 442 |
| [IQ0](IQ0.txt) | 435 | 435 | 0 | 98 | 17 |
| [LS0](LS0.txt) | 418 | 302 | 116 | 182 | 115 |
| [TM0](TM0.txt) | 418 | 418 | 0 | 141 | 68 |
| [HI1](HI1.txt) | 414 | 396 | 18 | 88 | 56 |
| [HI0](HI0.txt) | 402 | 389 | 13 | 77 | 78 |
| [FWN](FWN.txt) | 377 | 273 | 104 | 280 | 190 |
| [BDR](BDR.txt) | 354 | 288 | 66 | 310 | 122 |
| [DMM](DMM.txt) | 318 | 261 | 57 | 264 | 128 |
| [XE2](XE2.txt) | 308 | 281 | 27 | 61 | 159 |
| [HW0](HW0.txt) | 298 | 291 | 7 | 107 | 52 |
| [DQC](DQC.txt) | 275 | 128 | 147 | 121 | 157 |
| [ICC](ICC.txt) | 269 | 261 | 8 | 177 | 36 |
| [CBB](CBB.txt) | 244 | 224 | 20 | 236 | 64 |
| [FIC](FIC.txt) | 240 | 218 | 22 | 181 | 50 |
| [BTC](BTC.txt) | 233 | 214 | 19 | 124 | 43 |
| [CDC](CDC.txt) | 229 | 216 | 13 | 229 | 64 |
| [FE0](FE0.txt) | 227 | 100 | 127 | 105 | 9 |
| [DLS](DLS.txt) | 202 | 193 | 9 | 182 | 45 |
| [BD0](BD0.txt) | 194 | 16 | 178 | 102 | 159 |
| [CSC](CSC.txt) | 178 | 141 | 37 | 178 | 92 |
| [IA0](IA0.txt) | 176 | 122 | 54 | 35 | 53 |
| [XEB](XEB.txt) | 161 | 144 | 17 | 156 | 31 |
| [TWC](TWC.txt) | 154 | 141 | 13 | 83 | 15 |
| [UNATTRIBUTED](UNATTRIBUTED.txt) | 142 | 135 | 7 | 0 | 2 |
| [CS1](CS1.txt) | 140 | 140 | 0 | 39 | 16 |
| [BA0](BA0.txt) | 133 | 11 | 122 | 55 | 123 |
| [HIC](HIC.txt) | 132 | 126 | 6 | 132 | 31 |
| [LQ0](LQ0.txt) | 123 | 117 | 6 | 63 | 52 |
| [DM0](DM0.txt) | 115 | 18 | 97 | 62 | 41 |
| [BDT](BDT.txt) | 113 | 113 | 0 | 113 | 28 |
| [JAB](JAB.txt) | 107 | 107 | 0 | 107 | 30 |
| [FDC](FDC.txt) | 100 | 100 | 0 | 63 | 11 |
| [CB0](CB0.txt) | 97 | 88 | 9 | 49 | 20 |
| [BT0](BT0.txt) | 95 | 6 | 89 | 35 | 79 |
| [HWC](HWC.txt) | 89 | 89 | 0 | 72 | 16 |
| [DC0](DC0.txt) | 85 | 44 | 41 | 60 | 45 |
| [DAE](DAE.txt) | 82 | 82 | 0 | 82 | 28 |
| [XEA](XEA.txt) | 78 | 78 | 0 | 78 | 18 |
| [PL0](PL0.txt) | 72 | 2 | 70 | 16 | 2 |
| [LL0](LL0.txt) | 69 | 51 | 18 | 69 | 68 |
| [XXA](XXA.txt) | 67 | 67 | 0 | 57 | 11 |
| [XE0](XE0.txt) | 60 | 42 | 18 | 60 | 40 |
| [FWC](FWC.txt) | 58 | 58 | 0 | 58 | 24 |
| [DQ0](DQ0.txt) | 53 | 51 | 2 | 44 | 15 |
| [TMC](TMC.txt) | 52 | 52 | 0 | 22 | 6 |
| [CB1](CB1.txt) | 46 | 44 | 2 | 46 | 10 |
| [FW0](FW0.txt) | 36 | 1 | 35 | 22 | 16 |
| [DA0](DA0.txt) | 30 | 28 | 2 | 30 | 18 |
| [DL0](DL0.txt) | 30 | 22 | 8 | 30 | 15 |
| [LQU](LQU.txt) | 29 | 26 | 3 | 29 | 11 |
| [CS0](CS0.txt) | 23 | 21 | 2 | 23 | 6 |
| [HDL](HDL.txt) | 20 | 12 | 8 | 20 | 11 |
| [FDL](FDL.txt) | 18 | 15 | 3 | 18 | 9 |
| [QAB](QAB.txt) | 18 | 18 | 0 | 18 | 3 |
| [CB3](CB3.txt) | 16 | 16 | 0 | 16 | 2 |
| [LFN](LFN.txt) | 16 | 16 | 0 | 16 | 1 |
| [DMC](DMC.txt) | 14 | 14 | 0 | 14 | 0 |
| [FI1](FI1.txt) | 12 | 1 | 11 | 12 | 12 |
| [FA0](FA0.txt) | 10 | 10 | 0 | 10 | 3 |
| [HW2](HW2.txt) | 8 | 8 | 0 | 8 | 3 |
| [FI0](FI0.txt) | 5 | 2 | 3 | 5 | 3 |
| [FW2](FW2.txt) | 5 | 5 | 0 | 5 | 5 |
| [JAC](JAC.txt) | 4 | 4 | 0 | 4 | 0 |
| [XF0](XF0.txt) | 4 | 4 | 0 | 4 | 2 |
| [XXB](XXB.txt) | 4 | 4 | 0 | 4 | 2 |
| [CR0](CR0.txt) | 3 | 2 | 1 | 3 | 2 |

Reproduce with `python modules_split.py`.

Expressions are printed with depth/width/length caps; a wide clause ends in
`... N more...`.  For a faithful rendering of one statement use
`python netlist_slice.py --region <pass> --dump <addr0> <addr1>`.
