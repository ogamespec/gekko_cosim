#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decompile_model.py — декомпиляция нативного кода модели COSIM.m2630opt.Jul1599
==============================================================================
Модель — скомпилированная логика процессора GKO (PowerPC). Её исполняемый код —
линейные «ячейки» оценки логики:
  * комбинационные конусы:  lbz (входы) -> and/or/nor (SOP) -> stb (выход);
  * упаковка битов:         slwi/rlwimi собирают 32-битные векторы из проводов;
  * приоритетные декодеры:  cmplw/cmplwi + bne/b — каскады if/else-if,
                            выставляющие управляющие провода и константы;
  * защёлки/состояние:      stw/sth/stb 32/16/8-битных значений.

Декомпилятор исполняет код символически: регистры -> выражения над проводами
w(банк, смещение), константы и булевы операции; на инструкциях сохранения
выдаёт псевдокод в стиле Verilog.

Банки состояния (базовые регистры бутстрапа): r13..r20 = 8 банков по 0x10000.
"""
import struct
import sys

from capstone import Cs, CS_ARCH_PPC, CS_MODE_BIG_ENDIAN, CS_MODE_32

MODEL = "model/COSIM.m2630opt.Jul1599"
OUT = "model/COSIM.m2630opt.Jul1599.pseudo.txt"
md = Cs(CS_ARCH_PPC, CS_MODE_BIG_ENDIAN | CS_MODE_32)
md.detail = False

BANKS = {13: 0, 14: 1, 15: 2, 16: 3, 17: 4, 18: 5, 19: 6, 20: 7}

# ---------------------------------------------------------------------------
# Символические значения
# ('W', bank, off)        — 1-битный провод
# ('C', int)              — константа
# ('NOT', e), ('AND',a,b), ('OR',a,b), ('XOR',a,b)
# ('PACK', [(bit, expr),...]) — 32-битное значение с известными битами
# ('UNK',)
# ---------------------------------------------------------------------------

def simpl(e):
    t = e[0]
    if t == 'NOT':
        x = simpl(e[1])
        if x[0] == 'C': return ('C', 1 - x[1])
        if x[0] == 'NOT': return x[1]
        return ('NOT', x)
    if t == 'AND':
        a, b = simpl(e[1]), simpl(e[2])
        if a[0] == 'C':
            return ('C', 0) if a[1] == 0 else b
        if b[0] == 'C':
            return ('C', 0) if b[1] == 0 else a
        if a == b: return a
        if a[0] == 'NOT' and a[1] == b: return ('C', 0)
        if b[0] == 'NOT' and b[1] == a: return ('C', 0)
        return ('AND', a, b)
    if t == 'OR':
        a, b = simpl(e[1]), simpl(e[2])
        if a[0] == 'C':
            return ('C', 1) if a[1] == 1 else b
        if b[0] == 'C':
            return ('C', 1) if b[1] == 1 else a
        if a == b: return a
        if a[0] == 'NOT' and a[1] == b: return ('C', 1)
        if b[0] == 'NOT' and b[1] == a: return ('C', 1)
        return ('OR', a, b)
    if t == 'XOR':
        a, b = simpl(e[1]), simpl(e[2])
        if a[0] == 'C':
            return ('NOT', b) if a[1] == 1 else b
        if b[0] == 'C':
            return ('NOT', a) if b[1] == 1 else a
        if a == b: return ('C', 0)
        return ('XOR', a, b)
    return e


import pickle as _pickle

def _load_slotmap():
    """Строит карту слот->имя прямо из файла модели (таблица символов).
    Класс 0x70050000: слот = word1_lo; класс 0x02040000: слот = (байт8<<8)|word1_lo.
    Имена реконструируются по префиксному сжатию (keep)."""
    try:
        data = open(MODEL, 'rb').read()
    except Exception:
        return {}
    sec = data[0x4BA840:0x4BA840 + 0x5B76C]
    recs = []
    i = 0
    while i < len(sec) - 16:
        w0 = struct.unpack('>I', sec[i:i+4])[0]
        if w0 == 0x70050000:
            w1 = struct.unpack('>I', sec[i+4:i+8])[0]
            keep = sec[i+10]; ns = i+11; kind = 'A'
        elif w0 == 0x02040000:
            w1 = struct.unpack('>I', sec[i+4:i+8])[0]
            keep = sec[i+9]; ns = i+10; kind = 'B'
        else:
            i += 1; continue
        j = ns
        while j < len(sec) and 32 <= sec[j] < 127: j += 1
        if j < len(sec) and sec[j] == 0 and 1 <= j-ns <= 48:
            recs.append((w0, w1, sec[i+8] if kind == 'B' else None, keep, sec[ns:j].decode('latin1'), kind))
            i = j+1
        else:
            i += 1
    full = None
    slotmap = {}
    for w0, w1, b8, keep, nm, kind in recs:
        if keep == 0: full = nm
        elif full and keep <= len(full): full = full[:keep] + nm
        else: full = (full + '.' + nm) if full else None
        slot = (w1 & 0xFFFF) if kind == 'A' else ((b8 << 8) | (w1 & 0xFF))
        slotmap.setdefault(slot, full)
    return slotmap

_SLOTMAP = _load_slotmap()

def slot_name(bank, off):
    """Имя провода по (банк, смещение): слот = off (>=0) или off+0x10000."""
    s = off if off >= 0 else off + 0x10000
    return _SLOTMAP.get(s)

def fmt(e, names=None):
    """Форматирует выражение в читаемый вид."""
    t = e[0]
    if t == 'W':
        b, o = e[1], e[2]
        name = slot_name(b, o)
        if name:
            return name
        return "w[%d][%s]" % (b, ("%04x" % (o & 0xFFFF)) if o >= 0 else ("-%04x" % (-o & 0xFFFF)))
    if t == 'C':
        v = e[1]
        if v == 0: return "0"
        if v == 1: return "1"
        if v > 0xFFFF:
            return "0x%08x" % v
        return "0x%x" % v
    if t == 'REG':
        return "r%d" % e[1]
    if t == 'NOT':
        x = fmt(e[1], names)
        if x.startswith('(') or x.startswith('~'):
            return "~%s" % x
        return "~(%s)" % x
    if t == 'AND':
        return "(%s & %s)" % (fmt(e[1], names), fmt(e[2], names))
    if t == 'OR':
        return "(%s | %s)" % (fmt(e[1], names), fmt(e[2], names))
    if t == 'XOR':
        return "(%s ^ %s)" % (fmt(e[1], names), fmt(e[2], names))
    if t == 'PACK':
        parts = []
        for bit, x in sorted(e[1], reverse=True):
            parts.append("%d:%s" % (bit, fmt(x, names)))
        return "{%s}" % ", ".join(parts)
    if t == 'LD32':
        return "mem32[%d][%s]" % (e[1], ("%04x" % (e[2] & 0xFFFF)) if e[2] >= 0 else "-%04x" % (-e[2] & 0xFFFF))
    return "??"


def fmt_off(o):
    """Смещение в состоянии (для адресата сохранения)."""
    return ("%04x" % (o & 0xFFFF)) if o >= 0 else ("-%04x" % (-o & 0xFFFF))


# ---------------------------------------------------------------------------
# Декомпилятор
# ---------------------------------------------------------------------------
class Decomp:
    def __init__(self, data, names=None):
        self.data = data
        self.regs = {i: ('REG', i) for i in range(32)}
        self.names = names or {}
        self.out = []
        self.pending_cmp = None
        self.if_stack = []      # (bne_target, indent, else_open, cond_str, prev_cond)
        self.indent = 0
        self.events = []        # ('IF'|'ELSEIF'|'ELSE'|'ENDIF'|'STORE'|'NOTE', ...)
        self.cur_cond = ('C', 1)
        self.record = True

    def ev(self, e):
        if self.record:
            self.events.append(e)

    def wr(self, s=""):
        self.out.append("  " * self.indent + s)

    def reg(self, i):
        return self.regs.get(i, ('UNK',))

    def decode(self, addr):
        try:
            return next(md.disasm(self.data[addr:addr+4], addr))
        except StopIteration:
            return None

    def close_done_ifs(self, ip):
        """Закрывает if, чья цель bne уже пройдена (else-ветка завершена
        «проваливанием», без явного перехода)."""
        while self.if_stack:
            tgt, if_ind, else_open = self.if_stack[-1][:3]
            if ip > tgt or (ip == tgt and not else_open):
                self.indent = if_ind
                self.wr("}")
                self.ev(('ENDIF',))
                self.if_stack.pop()
            else:
                break

    def next_ins(self, addr):
        """Следующая декодируемая инструкция (пропуская патч-слоты).
        Возвращает (адрес, mnemonic, op_str)."""
        for off in range(0, 0x200, 4):
            ins = self.decode(addr + off)
            if ins is not None:
                return (addr + off, ins.mnemonic, ins.op_str)
        return None

    def run(self, start, end, label=""):
        self.wr("// ========== %s: 0x%x..0x%x ==========" % (label, start, end))
        addr = start
        while addr < end:
            self.close_done_ifs(addr)
            ins = self.decode(addr)
            if ins is None:
                self.wr("// @%08x: [патч-слот / данные]" % addr)
                addr += 4
                continue
            m, ops = ins.mnemonic, ins.op_str
            a = addr
            if m == 'lbz' or m == 'lbzu' or m == 'lhz' or m == 'lhz' or m == 'lwz' or m == 'lwzu' or m == 'lha':
                rd, rest = ops.split(',', 1)
                rest = rest.strip()
                try:
                    d, ra = rest.split('(')
                    ra = ra.rstrip(')')
                    d = int(d, 0)
                except Exception:
                    ra = '0'; d = 0
                ri = int(rd[1:])
                if ra in ('r13', 'r14', 'r15', 'r16', 'r17', 'r18', 'r19', 'r20'):
                    bank = BANKS[int(ra[1:])]
                    if m in ('lwz', 'lwzu'):
                        self.regs[ri] = ('LD32', bank, d)
                    else:
                        self.regs[ri] = ('W', bank, d)
                else:
                    self.regs[ri] = ('UNK',)
            elif m == 'li' or m == 'lis' or m == 'addi' or m == 'addis' or m == 'ori' or m == 'oris' or m == 'xori' or m == 'xoris':
                parts = [x.strip() for x in ops.split(',')]
                rd = parts[0]
                ri = int(rd[1:])
                if m in ('ori', 'oris', 'xori', 'xoris'):
                    # формат: rD, rS, imm — сворачиваем только константы
                    try:
                        v = int(parts[2], 0)
                    except Exception:
                        self.regs[ri] = ('UNK',)
                        addr += 4
                        continue
                    cur = self.reg(ri)
                    if cur[0] == 'C':
                        if m == 'oris': v <<= 16
                        if m == 'xoris': v <<= 16
                        v = (cur[1] | v) if m in ('ori', 'oris') else (cur[1] ^ v)
                        self.regs[ri] = ('C', v & 0xFFFFFFFF)
                    else:
                        self.regs[ri] = ('UNK',)
                else:
                    try:
                        v = int(parts[1], 0)
                    except Exception:
                        v = 0
                    if m in ('addi', 'addis'):
                        cur = self.reg(ri)
                        if cur[0] == 'C':
                            self.regs[ri] = ('C', (cur[1] + v) & 0xFFFFFFFF)
                        else:
                            self.regs[ri] = ('UNK',)
                    else:
                        self.regs[ri] = ('C', v & 0xFFFFFFFF)
            elif m == 'and' or m == 'andc' or m == 'or' or m == 'orc' or m == 'nor' or m == 'nand' or m == 'xor' or m == 'eqv':
                rd, rest = ops.split(',', 1)
                r1, r2 = [x.strip() for x in rest.split(',')]
                a1, a2 = self.reg(int(r1[1:])), self.reg(int(r2[1:]))
                if m == 'and': v = simpl(('AND', a1, a2))
                elif m == 'andc': v = simpl(('AND', a1, ('NOT', a2)))
                elif m == 'or': v = simpl(('OR', a1, a2))
                elif m == 'orc': v = simpl(('OR', a1, ('NOT', a2)))
                elif m == 'nor': v = simpl(('NOT', ('OR', a1, a2)))
                elif m == 'nand': v = simpl(('NOT', ('AND', a1, a2)))
                elif m == 'xor': v = simpl(('XOR', a1, a2))
                else: v = simpl(('NOT', ('XOR', a1, a2)))
                self.regs[int(rd[1:])] = v
            elif m == 'not':
                rd, r1 = ops.split(',')
                self.regs[int(rd[1:])] = simpl(('NOT', self.reg(int(r1.strip()[1:]))))
            elif m == 'slwi' or m == 'srwi' or m == 'srawi' or m == 'slli' or m == 'rlwinm':
                # сдвиги/маски: сохраняем как PACK/UNK
                rd, rest = ops.split(',', 1)
                try:
                    parts = [x.strip() for x in rest.split(',')]
                    rs = int(parts[0][1:])
                    sh = int(parts[1], 0)
                except Exception:
                    rs, sh = 0, 0
                ri = int(rd[1:])
                if m == 'slwi' and self.reg(rs)[0] in ('W', 'NOT', 'AND', 'OR', 'C'):
                    # rD = rS << sh: MSB бит (31-sh) <- бит 0 источника
                    self.regs[ri] = ('PACK', [(31 - sh, self.reg(rs))])
                else:
                    self.regs[ri] = ('UNK',)
            elif m == 'rlwimi':
                # rA = (rotl(rS,SH) & mask) | (rA & ~mask); при MB==ME==b и SH=31-b:
                # бит b регистра rA <- бит 0 источника (упаковка провода в вектор)
                rd, rest = ops.split(',', 1)
                rs, sh, mb, me = [x.strip() for x in rest.split(',')]
                ri = int(rd[1:])
                rs_i = int(rs[1:])
                mb_i = int(mb, 0); me_i = int(me, 0); sh_i = int(sh, 0)
                cur = self.regs.get(ri, ('C', 0))
                if mb_i == me_i and self.reg(rs_i)[0] in ('W', 'NOT', 'AND', 'OR', 'C'):
                    b = 31 - sh_i
                    if cur[0] == 'PACK':
                        bits = [(x, y) for x, y in cur[1] if x != b] + [(b, self.reg(rs_i))]
                    elif cur[0] == 'C':
                        bits = [(x, ('C', (cur[1] >> (31 - x)) & 1)) for x in range(32) if x != b]
                        bits.append((b, self.reg(rs_i)))
                    else:
                        bits = [(b, self.reg(rs_i))]
                    self.regs[ri] = ('PACK', bits)
                else:
                    self.regs[ri] = ('UNK',)
            elif m == 'stb' or m == 'stbu' or m == 'sth' or m == 'sth' or m == 'stw' or m == 'stwu':
                rs, rest = ops.split(',', 1)
                rest = rest.strip()
                try:
                    d, ra = rest.split('(')
                    ra = ra.rstrip(')')
                    d = int(d, 0)
                except Exception:
                    ra = '0'; d = 0
                if ra in ('r13', 'r14', 'r15', 'r16', 'r17', 'r18', 'r19', 'r20'):
                    bank = BANKS[int(ra[1:])]
                    v = self.reg(int(rs[1:]))
                    nm = slot_name(bank, d)
                    suffix = ("  // %s" % nm) if nm else ""
                    if m in ('stw', 'stwu'):
                        self.wr("// @%08x:  mem32[%d][%s] <= %s;%s" % (a, bank, fmt_off(d), fmt(v, self.names), suffix))
                        self.ev(('STORE', bank, d, fmt(v, self.names), 32, a))
                    else:
                        self.wr("// @%08x:  w[%d][%s]    <= %s;%s" % (a, bank, fmt_off(d), fmt(v, self.names), suffix))
                        self.ev(('STORE', bank, d, fmt(v, self.names), 1, a))
                else:
                    self.wr("// @%08x:  store %s -> %s(%s)  [база вне банков]" % (a, rs, d, ra))
            elif m == 'cmplw' or m == 'cmplwi' or m == 'cmpw' or m == 'cmpwi':
                r1, r2 = [x.strip() for x in ops.split(',')]
                try:
                    lhs = self.reg(int(r1[1:]))
                except Exception:
                    lhs = ('UNK',)
                if r2.startswith('r'):
                    rhs = self.reg(int(r2[1:]))
                else:
                    rhs = ('C', int(r2, 0) & 0xFFFFFFFF)
                self.pending_cmp = (lhs, rhs)
            elif m == 'bne' or m == 'beq':
                tgt = int(ops, 0)
                if tgt < a:
                    self.wr("// @%08x: %s 0x%x  [цикл назад]" % (a, m, tgt))
                    continue
                if self.pending_cmp is not None:
                    lhs, rhs = self.pending_cmp
                    self.pending_cmp = None
                    cond_s = "(%s == %s)" % (fmt(lhs, self.names), fmt(rhs, self.names))
                    if self.if_stack and self.if_stack[-1][2] is True:
                        # мы в else-ветке: склеиваем "} else {" + "if (" -> "} else if ("
                        if_ind = self.if_stack[-1][1]
                        self.out[-1] = "  " * if_ind + "else if %s {" % cond_s
                        self.ev(('ELSEIF', cond_s))
                        self.if_stack.append((tgt, if_ind, False, cond_s, self.cur_cond))
                        self.cur_cond = simpl(('AND', self.cur_cond, (lhs, rhs, '==') if False else ('EQ', lhs, rhs))) if False else self.cur_cond
                        self.indent = if_ind + 1
                    else:
                        self.wr("if %s {" % cond_s)
                        self.ev(('IF', cond_s))
                        self.if_stack.append((tgt, self.indent, False, cond_s, self.cur_cond))
                        self.cur_cond = ('EQ', lhs, rhs) if self.cur_cond == ('C', 1) else ('ANDC', self.cur_cond, ('EQ', lhs, rhs))
                        self.indent += 1
                else:
                    self.wr("// @%08x: if(??) goto 0x%x" % (a, tgt))
            elif m == 'b' and ops.startswith('0x'):
                tgt = int(ops, 0)
                if tgt < a:
                    self.wr("// @%08x: goto 0x%x  [цикл назад]" % (a, tgt))
                    continue
                if self.if_stack:
                    if_ind = self.if_stack[-1][1]
                    # цепочка продолжается (else), только если следующая
                    # инструкция стоит ровно по адресу цели bne
                    nx = self.next_ins(a + 4)
                    if nx and nx[0] == self.if_stack[-1][0]:
                        self.wr("} else {")
                        self.ev(('ELSE',))
                        self.indent = if_ind + 1
                        self.if_stack[-1] = (tgt, if_ind, True, self.if_stack[-1][3], self.if_stack[-1][4])
                    else:
                        self.indent = if_ind
                        self.wr("}")
                        self.ev(('ENDIF',))
                        self.if_stack.pop()
                else:
                    self.wr("// @%08x: goto 0x%x" % (a, tgt))
            elif m.startswith('b') or m.startswith('bc'):
                self.wr("// @%08x: %s %s  [условный/иной переход]" % (a, m, ops))
            elif m == 'rlwimi':
                pass
            addr += 4
        while self.if_stack:
            self.indent -= 1
            self.wr("}")
            self.ev(('ENDIF',))
            self.if_stack.pop()
        self.wr("// конец региона")


HEADER = """ПСЕВДОДЕКОМПИЛЯЦИЯ НАТИВНОГО КОДА МОДЕЛИ COSIM.m2630opt.Jul1599
============================================================================
Код модели — линейные «ячейки» скомпилированной логики процессора GKO:
  * комбинационные конусы:  w[б][смещ] <= (терм1) | (терм2) | ...  (SOP),
    терм = (произведение проводов) & разрешение;
  * упаковка битов:         slwi/rlwimi собирают 32-битный вектор из проводов
    {бит:провод, ...};  семантика rlwimi: SH=31-b => бит b <- провод;
  * приоритетные декодеры:  if (вектор == конст) {...} else if (...) {...}
    (биты вектора = запросы, цепочка тестов = приоритетный выбор);
  * многобитные поля:       mem32[б][смещ] <= константа (stw 32 бита).

НОТАЦИЯ:
  w[б][смещ]   — 1-битный провод в банке состояния б (r13..r20 -> 0..7)
                 по смещению 'смещ' (hex, отрицательные — относительно
                 начала банка, т.е. 0x28000-|смещ| для банка 2);
  ИМЕНА: слот провода = смещ (>=0) или смещ+0x10000; имена взяты из
  таблицы символов модели: класс 0x7005 -> слот = word1_lo;
  класс 0x0204 -> слот = (байт8 << 8) | word1_lo.
  Именованные провода печатаются как GKO.<блок>...; безымянные — w[б][смещ].
  Один провод может читаться/писаться из нескольких банков-плоскостей
  (двухфазная двухзначная симуляция: L1/L2-копии) — в Verilog это одна
  переменная.
  mem32[б][смещ] — 32-битное слово состояния (stw);
  rN           — регистр, значение которого не отслежено (вход блока);
  {31:w[..], 0:w[..]} — 32-битный вектор, собранный из проводов;
  [патч-слот]  — слово списка патчей (после загрузки — инструкция
                 ветвления; ячейки кода идут с шагом 0x80).

СООТВЕТСТВИЕ VERILOG (руководство):
  1. Каждый провод w[б][смещ] -> одна 1-битная wire/reg переменная;
  2. w[б][X] <= expr без обратной связи на себя -> assign;
  3. w[б][X] <= expr, где expr зависит от w[б][X] (или сохраняется
     между тактами) -> always @(posedge clk) / защёлка;
  4. {биты:провода} == конст -> casez/case (приоритетный декодер);
  5. mem32[б][смещ] -> reg [31:0];
  6. rN (неотслеженные) — входы блока: назовите их сами по смыслу
     (сигналы такта/сброса/разрешения), сверяясь с таблицей символов.
"""

def main():
    data = open(MODEL, "rb").read()
    names = {}
    dec = Decomp(data, names)
    out = [HEADER]
    dec.out = out
    regions = [
        (0x40B6AC, 0x40C200, "SOP-регион 0x40B6AC (комбинационная логика)"),
        (0x58000, 0x58900, "0x58000: SOP + упаковка битов (вектор запросов)"),
        (0x58900, 0x59200, "0x58900: приоритетный декодер if/else-if"),
    ]
    if len(sys.argv) >= 3:
        regions = [(int(sys.argv[1], 0), int(sys.argv[2], 0),
                    "регион %s..%s" % (sys.argv[1], sys.argv[2]))]
    for s, e, lab in regions:
        dec.run(s, e, lab)
    text = "\n".join(dec.out)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("written:", OUT, "(%d строк)" % len(dec.out))


if __name__ == "__main__":
    main()
