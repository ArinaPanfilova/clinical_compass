"""Извлечение ключевых сведений из медицинских документов (выписки, осмотры, направления).

Детерминированно: словари (extraction_terms.yaml) + регулярные выражения + обработка отрицаний,
сомнений, условных фраз и чужого анамнеза. LLM не участвует: по проектному документу ей нельзя
единолично доверять противопоказания.

Главное правило: «неизвестно» ≠ «нет». Факт, о котором документ молчит или говорит неуверенно,
— None; False только при явном отрицании. При противоречии в документе побеждает True.
У каждого извлечённого элемента есть цитата {start, end, quote}: text[start:end] == quote.
Всё извлечённое имеет статус «извлечено, не проверено» — его подтверждает врач.

Как устроено:
1. Текст приводится к нижнему регистру (длина сохраняется — позиции совпадают с исходником)
   и делится на предложения/строки (clause) и части по запятым (segment).
2. Находятся упоминания: диагнозы по названию и по коду МКБ-10, термины фактов безопасности,
   СКФ и стадии ХБП, препараты, аллергены, слова аллергологического анамнеза.
3. Для каждого упоминания решается его статус: чужой анамнез («у матери») → условное
   («при планировании…», «контроль…») → сомнение («не исключена») → отрицание → сомнение
   («?», «под вопросом», «предварительный») → утверждение.
4. Из статусов собирается результат в форме эталона synthetic/documents.py плюс цитаты.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import yaml

TERMS_PATH = Path(__file__).with_name("extraction_terms.yaml")
STATUS = "extracted_unverified"

# Код МКБ-10: буква (кириллические двойники — латиница) + 2 цифры [+ .подрубрика]
_CYR2LAT = str.maketrans("АВЕКМНОРСТХ", "ABEKMHOPCTX")
_ICD = re.compile(r"(?<![\w.])([A-TV-Z])(\d{2})(?:[.,](\d{1,2}))?(?![\w])")
_CLAUSE_SPLIT = re.compile(r"\n|;|(?<=[.!?])(?=\s+[A-ZА-ЯЁ«(])")
_SEGMENT_SPLIT = re.compile(r",(?!\d)")
_WORDS = re.compile(r"[^\W_]+")
_PARENS = re.compile(r"\([^()]*\)?")
_BARE = re.compile(r"[\s,:—–\-/.]*(?:(?:и|или|либо|а\s+также|также|в\s+анамнезе)[\s,:—–\-/.]*)*")
_QMARK_AFTER = re.compile(r"\s*\)?\s*\?")
_QMARK_BEFORE = re.compile(r"\?\s*\(?\s*$")
_DATE_NUM = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?![\d])")
_DATE_SHORT = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?(?![\d])")
_GFR = re.compile(r"(?:\bскф|\bр?скф|\begfr|\bgfr|клиренс\w*\s+креатинин\w*)\s*(?:\([^)]{0,20}\)\s*)?"
                  r"(?:[:=—–-]\s*|по\s+\w+[\s:=—–-]*)?(\d{1,3}(?:[.,]\d+)?)(?!\s*(?:мес|нед|дн|раз|год|лет|ч\b|%|\d))")
_CKD = re.compile(r"(?:\bхбп|хроническ\w*\s+болезн\w*\s+почек)(?:\s*,?\s*(?:(?:с|c)\s*|ст\.?\s*|стади\w*\s*)?"
                  r"(1|2|3\s*[абab]?|4|5)(?![\w]))?")


def _norm(text: str) -> str:
    """Нижний регистр и «ё» → «е» без изменения длины (позиции совпадают с исходником)."""
    out = []
    for ch in text:
        lo = ch.lower()
        out.append("е" if lo == "ё" else lo if len(lo) == 1 else ch)
    return "".join(out)


@lru_cache(maxsize=None)
def _lex() -> SimpleNamespace:
    with TERMS_PATH.open(encoding="utf-8") as f:
        T = yaml.safe_load(f)
    c = re.compile
    meds = []
    for m in T["medications"]:
        names = sorted({_norm(n) for n in m["names"]}, key=len, reverse=True)
        meds.append((m["mnn"], m["group"], c(r"(?<![\w-])(?:" + "|".join(map(re.escape, names)) + r")\w{0,3}(?![\w])")))
    neg = T["negation"]
    return SimpleNamespace(
        safety_keys=tuple(T["safety_keys"]),
        dx=[(d["code"], c(p)) for d in T["diagnoses"] for p in d["re"]],
        icd_safety=[(tuple(r["prefix"]), r["key"], r["value"]) for r in T["icd_safety"]],
        terms=[(key, t["polarity"], c(t["re"])) for key, lst in T["safety_terms"].items() for t in (lst or [])],
        maoi_class=c(T["maoi_class"]), intake=c(T["intake_verbs"]),
        meds=meds, med_group={m["mnn"]: m["group"] for m in T["medications"]},
        cancel=c(T["cancel_triggers"]), current=c(T["current_triggers"]), dose=c(T["dose"]),
        allergens=[(a["name"], c(a["re"])) for a in T["allergens"]],
        al_denial=c(T["allergy_denial_terms"]), al_ctx=c(T["allergy_context_terms"]),
        al_glue=c(r"[\s,;:—–\-/.]*(?:" + T["allergy_list_glue"] + r"[\s,;:—–\-/.]*)*"),
        al_section_denial=c(T["allergy_section_denial"]),
        post=c(neg["post"]), pre_list=c(neg["pre_list"]), pre_tight=c(neg["pre_tight"]), pseudo=c(neg["pseudo"]),
        uncertainty=c(T["uncertainty"]), preliminary=c(T["preliminary"]), sublabel=c(T["sublabel_reset"]),
        hypothetical=c(T["hypothetical"]), family_clause=c(T["family_clause"]),
        family_segment=c(T["family_segment"]), preg_history=c(T["pregnancy_history"]),
        months=tuple(T["months"]), ago_units=T["ago_units"], ago_numbers=T["ago_numbers"],
        ago=c(r"(?:(более|больше|свыше|менее|меньше|около)\s+)?(?:(\d+(?:[.,]\d+)?|"
              + "|".join(sorted(T["ago_numbers"], key=len, reverse=True)) + r")\s*)?"
              r"(" + "|".join(sorted(T["ago_units"], key=len, reverse=True)) + r")\w*\.?\s+назад|\b(позавчера|вчера|сегодня)\b"),
        date_txt=c(r"(\d{1,2})\s+(" + "|".join(T["months"]) + r")\w*\s+(\d{4})"),
    )


SAFETY_KEYS: tuple[str, ...] = _lex().safety_keys


@dataclass(eq=False)
class _M:
    """Упоминание в тексте."""
    start: int
    end: int
    layer: str                    # concept | code | drug | allergen | atrig
    code: str | None = None       # код МКБ-10 (диагноз)
    dx: bool = False
    key: str | None = None        # факт безопасности термина
    value: bool | None = True     # что термин утверждает (СКФ ≥ 60 → False)
    polarity: str = "both"        # both | neg_only
    kind: str = ""                # maoi_class | gfr | denial | ctx
    mnn: str | None = None
    name: str | None = None       # аллерген
    status: str = "affirmed"      # affirmed | negated | uncertain | hypothetical | family
    trig: tuple[int, int] | None = None
    link: "_M | None" = None      # название ↔ код


class _Doc:
    def __init__(self, text: str):
        self.text, self.n = text, _norm(text)
        self.clauses, s = [], 0
        for m in _CLAUSE_SPLIT.finditer(text):
            self.clauses.append((s, m.start()))
            s = m.end()
        self.clauses.append((s, len(text)))
        self.clause_starts = [a for a, _ in self.clauses]
        self.segments = []
        for a, b in self.clauses:
            s = a
            for m in _SEGMENT_SPLIT.finditer(text, a, b):
                self.segments.append((s, m.start()))
                s = m.end()
            self.segments.append((s, b))
        self.seg_starts = [a for a, _ in self.segments]
        self.paragraphs = self._paragraphs()

    def clause(self, pos: int) -> tuple[int, int]:
        return self.clauses[bisect.bisect_right(self.clause_starts, pos) - 1]

    def segment(self, pos: int) -> tuple[int, int]:
        return self.segments[bisect.bisect_right(self.seg_starts, pos) - 1]

    def _paragraphs(self):
        """(начало, конец, заголовок в нижнем регистре или '', конец строки заголовка)."""
        out, s = [], 0
        for m in list(re.finditer(r"\n[ \t]*\n", self.text)) + [None]:
            e = m.start() if m else len(self.text)
            first_end = self.text.find("\n", s, e)
            first_end = e if first_end < 0 else first_end
            line = self.text[s:first_end].strip()
            header = ""
            if line and len(_WORDS.findall(line)) <= 6 and not re.search(r"\d", line) and (
                    (line.upper() == line and re.search(r"[A-ZА-ЯЁ]", line)) or line.endswith(":")):
                header = _norm(line)
            out.append((s, e, header, first_end))
            s = m.end() if m else e
        return out

    def section_header(self, pos: int) -> str:
        for s, e, header, hend in self.paragraphs:
            if s <= pos < e or (pos == e == len(self.text)):
                return header if pos >= hend else ""
        return ""

    def ev(self, start: int, end: int) -> dict:
        t = self.text
        while start < end and t[start] in " \t\n,;:—–-":
            start += 1
        while end > start and t[end - 1] in " \t\n,;:—–-(":
            end -= 1
        return {"start": start, "end": end, "quote": t[start:end]}


# --- Поиск упоминаний -------------------------------------------------------------------------

def _resolve_overlaps(cands: list[_M]) -> list[_M]:
    """Из перекрывающихся оставить более длинное (при равной длине — раньше найденное)."""
    order = sorted(range(len(cands)), key=lambda i: (-(cands[i].end - cands[i].start), i))
    taken: list[_M] = []
    for i in order:
        m = cands[i]
        if all(m.end <= t.start or m.start >= t.end for t in taken):
            taken.append(m)
    return sorted(taken, key=lambda m: m.start)


def _find_concepts(doc: _Doc, L) -> list[_M]:
    n, cands = doc.n, []
    for code, rx in L.dx:
        cands += [_M(m.start(), m.end(), "concept", code=code, dx=True) for m in rx.finditer(n)]
    for m in _CKD.finditer(n):
        st = (m.group(1) or "").replace(" ", "")
        code = f"N18.{st[0]}" if st else "N18.9"
        cands.append(_M(m.start(), m.end(), "concept", code=code, dx=True))
    for m in _GFR.finditer(n):
        v = float(m.group(1).replace(",", "."))
        cands.append(_M(m.start(), m.end(), "concept", key="renal_gfr_below_60", value=v < 60, kind="gfr"))
    for key, pol, rx in L.terms:
        for m in rx.finditer(n):
            if key == "pregnancy" and L.preg_history.match(n, m.end()):
                continue        # «беременностей 2» — акушерский анамнез
            cands.append(_M(m.start(), m.end(), "concept", key=key, polarity=pol))
    cands += [_M(m.start(), m.end(), "concept", key="maoi_within_2_weeks", polarity="neg_only", kind="maoi_class")
              for m in L.maoi_class.finditer(n)]
    return _resolve_overlaps(cands)


def _find_codes(doc: _Doc) -> list[_M]:
    out = []
    for m in _ICD.finditer(doc.text.translate(_CYR2LAT)):
        if "витамин" in doc.n[max(0, m.start() - 12):m.start()]:
            continue
        code = m.group(1) + m.group(2) + (f".{m.group(3)}" if m.group(3) else "")
        out.append(_M(m.start(), m.end(), "code", code=code, dx=True))
    return out


def _link_codes(doc: _Doc, names: list[_M], codes: list[_M]) -> None:
    """Название и код рядом — один диагноз с кодом из текста.

    Код в скобках «… (F41.1)» относится к названию перед ним; код без скобок — к названию сразу
    после него («E11.9 Сахарный диабет»), а если после него названия нет — к названию перед ним."""
    n = doc.n
    dx_all = sorted(names + codes, key=lambda m: m.start)

    def neighbours(c):
        i = dx_all.index(c)
        prev = dx_all[i - 1] if i > 0 and dx_all[i - 1].layer == "concept" else None
        nxt = dx_all[i + 1] if i + 1 < len(dx_all) and dx_all[i + 1].layer == "concept" else None
        cl = doc.clause(c.start)
        prev = prev if prev and doc.clause(prev.start) == cl and not prev.link else None
        nxt = nxt if nxt and doc.clause(nxt.start) == cl and not nxt.link else None
        return prev, nxt

    for c in codes:
        prev, nxt = neighbours(c)
        in_paren = n[:c.start].rstrip().endswith(("(", "["))
        target = None
        if in_paren and prev:
            gap = _PARENS.sub(" ", n[prev.end:c.start])
            if len(n[prev.end:c.start]) <= 60 and not _SEGMENT_SPLIT.search(gap):
                target = prev
        elif nxt and re.fullmatch(r"[\s:—–\-)\]]*", n[c.end:nxt.start]):
            target = nxt
        elif prev and re.fullmatch(r"[\s:—–\-(\[]*", n[prev.end:c.start]):
            target = prev
        if target:
            target.link, c.link = c, target


# --- Статус упоминаний ------------------------------------------------------------------------

def _assign_status(doc: _Doc, mentions: list[_M], L) -> None:
    n = doc.n
    # Перекрывающиеся упоминания разных слоёв («Аллергия на Авиандр») получают общий статус
    groups: list[list[_M]] = []
    for m in sorted(mentions, key=lambda m: (m.start, -m.end)):
        if groups and m.start < max(x.end for x in groups[-1]):
            groups[-1].append(m)
        else:
            groups.append([m])
    spans = [(min(x.start for x in g), max(x.end for x in g)) for g in groups]
    starts = [s for s, _ in spans]
    verdict: dict[int, tuple[str, tuple[int, int]]] = {}

    def overlaps_span(a, b):
        i = bisect.bisect_right(starts, b) - 1
        return i >= 0 and spans[i][1] > a and spans[i][0] < b

    def words(a, b):
        return len(_WORDS.findall(n[a:b]))

    def bare(a, b):
        return _BARE.fullmatch(_PARENS.sub(" ", n[a:b])) is not None

    def in_clause(i, clause):
        return clause[0] <= spans[i][0] and spans[i][1] <= clause[1]

    pseudo = [(m.start(), m.end()) for m in L.pseudo.finditer(n)]

    def in_pseudo(a, b):
        return any(a < pe and b > ps for ps, pe in pseudo)

    # сомнение «не исключена»
    for ps, pe in pseudo:
        cl = doc.clause(ps)
        i = bisect.bisect_right(starts, ps) - 1
        if i >= 0 and in_clause(i, cl) and spans[i][1] <= ps and words(spans[i][1], ps) <= 2 and "," not in n[spans[i][1]:ps]:
            verdict.setdefault(i, ("uncertain", (ps, pe)))
        j = bisect.bisect_left(starts, pe)
        if j < len(spans) and in_clause(j, cl) and words(pe, spans[j][0]) <= 2 and "," not in n[pe:spans[j][0]]:
            verdict.setdefault(j, ("uncertain", (ps, pe)))

    used_pos: list[tuple[int, int]] = []

    def mark(idx, trig):
        verdict.setdefault(idx, ("negated", trig))

    # отрицание после термина (с распространением назад по перечню)
    for m in L.post.finditer(n):
        a, b = m.start(), m.end()
        if overlaps_span(a, b) or in_pseudo(a, b):
            continue
        cl = doc.clause(a)
        i = bisect.bisect_right(starts, a) - 1
        if i < 0 or not in_clause(i, cl) or spans[i][1] > a:
            continue
        if words(spans[i][1], a) > 2 or "," in n[spans[i][1]:a]:
            continue
        mark(i, (a, b))
        k = i - 1
        while k >= 0 and in_clause(k, cl) and bare(spans[k][1], spans[k + 1][0]):
            mark(k, (a, b))
            k -= 1
        used_pos.append((a, b))

    def used(a, b):
        return any(a < ue and b > us for us, ue in used_pos)

    # отрицание перед перечнем («отрицает эпилепсию, ЧМТ»)
    for m in L.pre_list.finditer(n):
        a, b = m.start(), m.end()
        if overlaps_span(a, b) or in_pseudo(a, b) or used(a, b):
            continue
        cl = doc.clause(a)
        j = bisect.bisect_left(starts, b)
        if j >= len(spans) or not in_clause(j, cl) or words(b, spans[j][0]) > 2 or "," in n[b:spans[j][0]]:
            continue
        mark(j, (a, b))
        k = j + 1
        while k < len(spans) and in_clause(k, cl) and bare(spans[k - 1][1], spans[k][0]):
            mark(k, (a, b))
            k += 1
        used_pos.append((a, b))

    # «не/нет/без» непосредственно перед термином
    for m in L.pre_tight.finditer(n):
        a, b = m.start(), m.end()
        if overlaps_span(a, b) or in_pseudo(a, b) or used(a, b):
            continue
        cl = doc.clause(a)
        j = bisect.bisect_left(starts, b)
        if j < len(spans) and in_clause(j, cl) and words(b, spans[j][0]) <= 1 and "," not in n[b:spans[j][0]]:
            mark(j, (a, b))

    for gi, (g, (s, e)) in enumerate(zip(groups, spans)):
        cs, ce = doc.clause(s)
        ss, se = doc.segment(s)[0], doc.segment(max(s, e - 1))[1]   # название может содержать запятую
        status, trig = "affirmed", None
        prelim = [p for p in L.preliminary.finditer(n, cs, s)]
        if L.family_clause.search(n, cs, ce) or L.family_segment.search(n, ss, se):
            status = "family"
        elif L.hypothetical.search(n[ss:s]):
            status = "hypothetical"
        elif gi in verdict:
            status, trig = verdict[gi]
        elif (L.uncertainty.search(n, ss, se) or _QMARK_AFTER.match(n, e)
              or _QMARK_BEFORE.search(n[max(cs, s - 4):s])):
            status = "uncertain"
        elif prelim and not L.sublabel.search(n, prelim[-1].end(), s):
            status = "uncertain"
        for m in g:
            m.status, m.trig = status, trig


# --- Сборка результата ------------------------------------------------------------------------

def _icd_values(code: str, L) -> list[tuple[str, bool]]:
    return [(key, val) for prefixes, key, val in L.icd_safety if any(code.startswith(p) for p in prefixes)]


def _document_date(doc: _Doc, L) -> date | None:
    """Дата в строке со словом «дата», иначе в шапке (первые 2 строки или короткая строка из первых 4)."""
    best = None
    lines = []
    for m in re.finditer(r"[^\n]*", doc.text):
        if m.group().strip():
            lines.append((m.start(), m.end()))
        if len(lines) == 4:
            break
    head = [ln for i, ln in enumerate(lines) if i < 2 or ln[1] - ln[0] < 60]
    cands = []
    for m in _DATE_NUM.finditer(doc.n):
        y = int(m.group(3))
        cands.append((m.start(), m.end(), int(m.group(1)), int(m.group(2)), y + 2000 if y < 100 else y))
    for m in L.date_txt.finditer(doc.n):
        cands.append((m.start(), m.end(), int(m.group(1)), L.months.index(m.group(2)) + 1, int(m.group(3))))
    for s, e, d, mo, y in cands:
        line_s = doc.n.rfind("\n", 0, s) + 1
        line = doc.n[line_s:s]
        if re.search(r"(?:отмен\w*|\bотм\.|\bс|\bдо|\bпо)\s*$", line):
            continue            # дата отмены или начала приёма, а не документа
        if re.search(r"\bдат\w*", line):
            prio = 0
        elif any(a <= s < b for a, b in head):
            prio = 1
        else:
            continue
        try:
            dt = date(y, mo, d)
        except ValueError:
            continue
        if best is None or (prio, s) < best[0]:
            best = ((prio, s), dt)
    return best[1] if best else None


def _cancel_days(text: str, doc_date: date | None, L) -> float | None:
    """Сколько дней назад отменён препарат (по фрагменту после слова «отменён»), None — неизвестно."""
    d = _DATE_SHORT.search(text)
    r = L.ago.search(text)
    if r and (not d or r.start() < d.start()):
        if r.group(4):
            return {"сегодня": 0, "вчера": 1, "позавчера": 2}[r.group(4)]
        num = r.group(2)
        k = 1.0 if num is None else (L.ago_numbers[num] if num in L.ago_numbers else float(num.replace(",", ".")))
        unit = next(u for u in sorted(L.ago_units, key=len, reverse=True) if r.group(3).startswith(u))
        days = k * L.ago_units[unit]
        return days - 1 if r.group(1) in ("менее", "меньше") else days
    if d and doc_date:
        day, mon = int(d.group(1)), int(d.group(2))
        y = d.group(3)
        year = (int(y) + 2000 if len(y) == 2 else int(y)) if y else doc_date.year
        try:
            cd = date(year, mon, day)
        except ValueError:
            return None
        if not y and cd > doc_date:
            cd = date(year - 1, mon, day)
        days = (doc_date - cd).days
        return days if days >= 0 else None
    return None


def extract(text: str) -> dict:
    """Ключевые сведения документа в форме эталона synthetic/documents.py с цитатами.

    Возвращает: diagnoses [{code, status, evidence}], medications [{mnn, dose_mg, status, evidence}],
    allergies [{name, evidence}] | [] | None, allergies_evidence, safety {key: {value, evidence}},
    document_date (ISO | None), status = "extracted_unverified". Формат — docs/API_CONTRACT.md."""
    L = _lex()
    text = text or ""
    doc = _Doc(text)
    n = doc.n

    concepts = _find_concepts(doc, L)
    codes = _find_codes(doc)
    _link_codes(doc, [c for c in concepts if c.dx], codes)
    drugs = _resolve_overlaps([_M(m.start(), m.end(), "drug", mnn=mnn)
                               for mnn, _group, rx in L.meds for m in rx.finditer(n)])
    allergens = _resolve_overlaps([_M(m.start(), m.end(), "allergen", name=name)
                                   for name, rx in L.allergens for m in rx.finditer(n)])
    atrigs = _resolve_overlaps(
        [_M(m.start(), m.end(), "atrig", kind="denial") for m in L.al_denial.finditer(n)]
        + [_M(m.start(), m.end(), "atrig", kind="ctx") for m in L.al_ctx.finditer(n)])
    _assign_status(doc, concepts + codes + drugs + allergens + atrigs, L)
    doc_date = _document_date(doc, L)

    # --- аллергии
    accepted: list[_M] = []
    denial = None
    cand_all = sorted(allergens + drugs, key=lambda m: m.start)
    ok = ("affirmed", "uncertain", "hypothetical")
    for t in atrigs:
        if t.kind == "denial" and t.status == "negated" and denial is None:
            denial = doc.ev(min(t.start, t.trig[0]), max(t.end, t.trig[1]))
        if t.status not in ("affirmed", "uncertain"):
            continue
        cs, ce = doc.clause(t.start)
        prev = t.end
        for c in cand_all:
            if c.start < t.end or c.start >= ce:
                continue
            if not L.al_glue.fullmatch(_PARENS.sub(" ", n[prev:c.start])):
                break
            if c.status in ok and c not in accepted:
                accepted.append(c)
            prev = c.end
    for cs, ce in doc.clauses:
        if "аллерг" not in doc.section_header(cs) or n[cs:ce].strip() == doc.section_header(cs).strip():
            continue
        inside = [c for c in cand_all if cs <= c.start < ce and c.status in ok]
        accepted += [c for c in inside if c not in accepted]
        if not inside and denial is None and L.al_section_denial.search(n[cs:ce]):
            denial = doc.ev(cs, ce)
    names: dict[str, dict] = {}
    for c in sorted(accepted, key=lambda m: m.start):
        name = c.name or c.mnn
        names.setdefault(name, {"name": name, "evidence": doc.ev(c.start, c.end)})
    if names:
        allergies, allergies_ev = list(names.values()), None
    elif denial:
        allergies, allergies_ev = [], denial
    else:
        allergies, allergies_ev = None, None

    # --- препараты
    med_mentions = [d for d in drugs if d not in accepted and d.status not in ("negated", "family")]
    per_mnn: dict[str, list[dict]] = {}
    for d in med_mentions:
        ss, _ = doc.segment(d.start)
        cs, ce = doc.clause(d.start)
        end = ce
        for o in drugs:
            if o.start > d.start and o.start < ce:
                os_, _ = doc.segment(o.start)
                end = o.start if os_ == ss else os_
                break
        window = n[ss:end]
        label = n[cs:ss]
        label = label[:label.find(":")] if ":" in label else ""
        sub = _sub_header(doc, d.start)
        cancel = L.cancel.search(window) or L.cancel.search(label) or L.cancel.search(sub)
        current = L.current.search(window)
        status = "cancelled" if cancel and not current else "current"
        dm = L.dose.search(n, d.end, end)
        dose = None
        if dm:
            dose = float(dm.group(1).replace(",", "."))
            dose = dose / 1000 if dm.group(2) in ("мкг", "mcg") else dose * 1000 if dm.group(2) == "г" else dose
            dose = int(dose) if dose == int(dose) else dose
        days = None
        if status == "cancelled":
            cm = L.cancel.search(window)
            days = _cancel_days(window[cm.start():] if cm else window, doc_date, L)
        per_mnn.setdefault(d.mnn, []).append({"status": status, "dose": dose, "days": days,
                                              "ev": doc.ev(d.start, end), "pos": d.start})
    medications = []
    maoi_vals: list[tuple[bool | None, dict]] = []
    for mnn, lst in per_mnn.items():
        status = "current" if any(x["status"] == "current" for x in lst) else "cancelled"
        mine = [x for x in lst if x["status"] == status]
        dose = next((x["dose"] for x in mine if x["dose"] is not None),
                    next((x["dose"] for x in lst if x["dose"] is not None), None))
        medications.append({"mnn": mnn, "dose_mg": dose, "status": status, "evidence": mine[0]["ev"]})
        if L.med_group.get(mnn) == "maoi":
            if status == "current":
                maoi_vals.append((True, mine[0]["ev"]))
            else:
                known = [x["days"] for x in mine if x["days"] is not None]
                maoi_vals.append(((min(known) < 14) if known else None, mine[0]["ev"]))
    medications.sort(key=lambda m: m["evidence"]["start"])

    # --- диагнозы
    dx: dict[str, dict] = {}
    for m in sorted(concepts + codes, key=lambda m: m.start):
        if not m.dx or (m.layer == "code" and m.link):
            continue
        code = m.link.code if m.link else m.code
        status = m.status
        if m.link and status == "affirmed" and m.link.status == "uncertain":
            status = "uncertain"
        if status not in ("affirmed", "uncertain"):
            continue
        st = "suspected" if status == "uncertain" else "confirmed"
        span = (min(m.start, m.link.start), max(m.end, m.link.end)) if m.link else (m.start, m.end)
        if code not in dx:
            dx[code] = {"code": code, "status": st, "evidence": doc.ev(*span)}
        elif st == "suspected":
            dx[code]["status"] = "suspected"      # осторожнее: сомнение в одном месте снимает «подтверждён»

    # --- факты безопасности
    contrib: dict[str, list[tuple[bool, dict]]] = {k: [] for k in SAFETY_KEYS}
    for m in concepts + codes:
        if m.layer == "code" and m.link:
            continue
        if m.kind == "maoi_class":
            continue
        if m.dx:
            vals = _icd_values(m.link.code if m.link else m.code, L)
        else:
            vals = [(m.key, m.value)]
        if m.status == "affirmed" and m.polarity == "both":
            span = (min(m.start, m.link.start), max(m.end, m.link.end)) if m.link else (m.start, m.end)
            for key, val in vals:
                contrib[key].append((val, doc.ev(*span)))
        elif m.status == "negated":
            for key, val in vals:
                if val is True:
                    contrib[key].append((False, doc.ev(min(m.start, m.trig[0]), max(m.end, m.trig[1]))))
    for c in accepted:
        if (c.mnn or c.name) == "авиандр":
            contrib["hypersensitivity_aviandr"].append((True, doc.ev(c.start, c.end)))

    safety = {}
    for k in SAFETY_KEYS:
        vals = contrib[k]
        hit = next((v for v in vals if v[0] is True), None) or next((v for v in vals if v[0] is False), None)
        safety[k] = {"value": hit[0], "evidence": hit[1]} if hit else {"value": None, "evidence": None}

    # ингибиторы МАО: приём или отмена < 14 дней назад; срок неизвестен — None
    maoi = None
    if maoi_vals:
        tv = [v for v in maoi_vals if v[0] is True]
        nv = [v for v in maoi_vals if v[0] is None]
        maoi = tv[0] if tv else nv[0] if nv else maoi_vals[0]
    else:
        for m in concepts:
            if m.kind != "maoi_class":
                continue
            ss, se = doc.segment(m.start)
            if m.status == "negated" and maoi is None:
                maoi = (False, doc.ev(min(m.start, m.trig[0]), max(m.end, m.trig[1])))
            elif m.status == "affirmed" and L.intake.search(n, ss, se):
                maoi = (True, doc.ev(m.start, m.end))
                break
    safety["maoi_within_2_weeks"] = {"value": maoi[0], "evidence": maoi[1] if maoi[0] is not None else None} \
        if maoi else {"value": None, "evidence": None}

    return {
        "diagnoses": list(dx.values()),
        "medications": medications,
        "allergies": allergies,
        "allergies_evidence": allergies_ev,
        "safety": safety,
        "document_date": doc_date.isoformat() if doc_date else None,
        "status": STATUS,
    }


def _sub_header(doc: _Doc, pos: int) -> str:
    """Ближайшая строка-подзаголовок «…:» выше в том же абзаце («Отменённые препараты:»)."""
    for s, e, _h, _he in doc.paragraphs:
        if s <= pos < e:
            line_start = doc.n.rfind("\n", s, pos)
            above = doc.n[s:line_start] if line_start >= 0 else ""
            return next((ln for ln in reversed(above.splitlines()) if ln.strip().endswith(":")), "")
    return ""
