# Трек А: ядро аналитики Авиандра и синтетическая когорта — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Чистые функции аналитики применения препарата по курсам терапии (KPI, траектории, ответ, приверженность, безопасность, индекс устойчивой пользы, k-анонимность) и генератор синтетической когорты курсов Авиандра.

**Architecture:** Новый модуль `kompas_core/analytics.py` без БД и сети, вход — список словарей-курсов. Генератор `synthetic/aviandr_cohort.py` выдаёт курсы в том же формате. Сервер (трек Б) позже собирает курсы из своих таблиц и вызывает `aviandr_report`. Существующий код ядра не меняется, кроме экспорта в `kompas_core/__init__.py`.

**Tech Stack:** Python 3.12, stdlib (`statistics`, `math`, `random`), PyYAML (уже есть), pytest.

Спек: `docs/superpowers/specs/2026-10-26-kompas-tz-completion-design.md`, блок 2.

**Правило проекта:** сначала тесты, они должны упасть по правильной причине (нет модуля/функции), потом код. Перед коммитом — весь набор `python -m pytest -q`.

**Окружение:** venv `/home/lyssten/projects/Hack-Compass/.ref/venv` (pyyaml, pytest уже стоят). Запуск тестов из корня репо:
`/home/lyssten/projects/Hack-Compass/.ref/venv/bin/python -m pytest -q`

**Git:** ветка `agent/claude/tz-completion` уже активна, identity настроена. Коммиты без строк Co-Authored-By.

## Формат курса (вход аналитики)

```python
{
  "course_id": "AV-0001",
  "patient_key": "AVP-0001",           # сервер для исследователя заменит псевдонимом
  "doctor_id": "doc-ivanova",
  "drug_id": "aviandr",
  "age": 34, "sex": "Ж",               # "Ж" | "М"
  "indication": "F41.1",               # "F41.1" | "F43.2"
  "comorbidities": ["cardiovascular"], # подмножество {"cardiovascular", "endocrine"}; [] = нет
  "concomitant": ["antidepressant"],   # [] = нет
  "start_date": "2026-03-02",          # ISO
  "end_date": None,                    # None = курс идёт
  "planned_weeks": 8,
  "stop_reason": None,                 # None | completed | adverse_event | inefficacy | improvement | switch | lost_to_followup
  "visits": [{"week": 0, "gad7": 15, "phq9": 9}, {"week": 2, "gad7": None, "phq9": None}],  # None = анкета не пришла
  "intake": {"taken": 50, "missed": 4, "unknown": 2},
  "adverse_events": [{"term": "сонливость", "severity": "mild", "serious": False, "week": 1}],
}
```

## Файлы

- Create: `kompas_core/analytics.py` — все функции аналитики.
- Create: `tests/test_analytics.py`
- Create: `synthetic/aviandr_cohort.py` — генератор курсов.
- Create: `tests/test_aviandr_cohort.py`
- Modify: `kompas_core/__init__.py` — экспорт `aviandr_report`.
- Modify: `docs/API_CONTRACT.md` — раздел «Курсы для аналитики».

---

### Task 1: Тесты ядра аналитики (красные)

**Files:**
- Create: `tests/test_analytics.py`

- [ ] **Step 1: Написать тесты**

```python
"""Аналитика применения препарата по курсам терапии."""
import pytest

from kompas_core.analytics import (
    outcome_group, filter_courses, kpis, trajectories, response_rates, adherence,
    safety, benefit_index, composition, wilson, aviandr_report, CAVEAT,
)


def mk(i=0, *, age=40, sex="Ж", indication="F41.1", comorbidities=(), concomitant=(),
       start="2026-05-01", stop=None, visits=((0, 16, 10), (2, 12, 8), (4, 8, 6)),
       intake=(50, 4, 2), aes=(), doctor="doc-a"):
    """Курс с визитами (неделя, GAD-7, PHQ-9) и НЯ (term, severity, serious)."""
    return {
        "course_id": f"C-{i}", "patient_key": f"K-{i}", "doctor_id": doctor, "drug_id": "aviandr",
        "age": age, "sex": sex, "indication": indication,
        "comorbidities": list(comorbidities), "concomitant": list(concomitant),
        "start_date": start, "end_date": None if stop is None else "2026-06-01",
        "planned_weeks": 8, "stop_reason": stop,
        "visits": [{"week": w, "gad7": g, "phq9": p} for w, g, p in visits],
        "intake": {"taken": intake[0], "missed": intake[1], "unknown": intake[2]},
        "adverse_events": [{"term": t, "severity": s, "serious": ser, "week": 1} for t, s, ser in aes],
    }


# ---------- Группы исхода и фильтры ----------

@pytest.mark.parametrize("reason,group", [
    (None, "continued"), ("completed", "continued"), ("adverse_event", "stopped_ae"),
    ("inefficacy", "stopped_inefficacy"), ("switch", "stopped_other"),
    ("improvement", "stopped_other"), ("lost_to_followup", "stopped_other")])
def test_outcome_group(reason, group):
    assert outcome_group(mk(stop=reason)) == group


def test_filter_by_demographics_and_indication():
    cs = [mk(1, age=25, sex="Ж"), mk(2, age=55, sex="М"), mk(3, age=70, sex="Ж", indication="F43.2")]
    assert [c["course_id"] for c in filter_courses(cs, {"sex": "Ж"})] == ["C-1", "C-3"]
    assert [c["course_id"] for c in filter_courses(cs, {"age_min": 50, "age_max": 69})] == ["C-2"]
    assert [c["course_id"] for c in filter_courses(cs, {"indication": "F43.2"})] == ["C-3"]


def test_filter_comorbidity_none_means_empty_list():
    cs = [mk(1), mk(2, comorbidities=["cardiovascular"]), mk(3, comorbidities=["endocrine"])]
    assert [c["course_id"] for c in filter_courses(cs, {"comorbidity": "none"})] == ["C-1"]
    assert [c["course_id"] for c in filter_courses(cs, {"comorbidity": "endocrine"})] == ["C-3"]


def test_filter_concomitant_period_and_doctor():
    cs = [mk(1, start="2026-01-10", doctor="doc-a"), mk(2, start="2026-04-01", concomitant=["antidepressant"], doctor="doc-b")]
    assert [c["course_id"] for c in filter_courses(cs, {"concomitant": "antidepressant"})] == ["C-2"]
    assert [c["course_id"] for c in filter_courses(cs, {"start_from": "2026-03-01"})] == ["C-2"]
    assert [c["course_id"] for c in filter_courses(cs, {"start_to": "2026-03-01"})] == ["C-1"]
    assert [c["course_id"] for c in filter_courses(cs, {"doctor_id": "doc-a"})] == ["C-1"]


def test_filter_ignores_empty_values():
    cs = [mk(1), mk(2)]
    assert len(filter_courses(cs, {"sex": "", "indication": None, "comorbidity": "all"})) == 2
    assert len(filter_courses(cs, None)) == 2


# ---------- KPI ----------

def test_kpis_counts_by_status():
    cs = [mk(1), mk(2), mk(3, stop="completed"), mk(4, stop="adverse_event"),
          mk(5, stop="adverse_event"), mk(6, stop="inefficacy"), mk(7, stop="lost_to_followup")]
    k = kpis(cs)
    assert k["assigned"] == 7 and k["active"] == 2 and k["completed"] == 1 and k["discontinued"] == 4
    assert k["by_reason"]["adverse_event"] == 2 and k["by_reason"]["inefficacy"] == 1
    assert k["by_reason"]["switch"] == 0 and "completed" not in k["by_reason"]


# ---------- Траектории ----------

def test_trajectories_median_and_quartiles_per_group():
    cs = [mk(1, visits=((0, 10, 5), (2, 8, 5))), mk(2, visits=((0, 14, 5), (2, 10, 5))),
          mk(3, visits=((0, 18, 5), (2, None, None))), mk(4, stop="adverse_event", visits=((0, 20, 9),))]
    t = trajectories(cs, "gad7")
    w0 = t["continued"][0]
    assert (w0["week"], w0["n"], w0["median"], w0["q1"], w0["q3"]) == (0, 3, 14, 12, 16)
    w2 = t["continued"][1]
    assert (w2["week"], w2["n"], w2["median"]) == (2, 2, 9)          # пропуск не считается нулём
    assert t["stopped_ae"] == [{"week": 0, "n": 1, "median": 20, "q1": 20, "q3": 20, "hidden": False}]
    assert t["stopped_inefficacy"] == []


def test_trajectories_hide_points_below_k():
    cs = [mk(i, visits=((0, 10 + i, 5),)) for i in range(4)]
    p = trajectories(cs, "gad7", k_min=5)["continued"][0]
    assert p == {"week": 0, "n": None, "median": None, "q1": None, "q3": None, "hidden": True}


# ---------- Ответ, ремиссия, ДИ ----------

def test_wilson_known_values():
    assert wilson(50, 100) == [0.404, 0.596]
    assert wilson(0, 10) == [0.0, 0.278]
    assert wilson(0, 0) is None


def test_response_rates_itt():
    cs = [mk(1, visits=((0, 16, 9), (8, 8, 4))),     # −50 %: ответ, MCID, не ремиссия (8 ≥ 5)
          mk(2, visits=((0, 16, 9), (8, 12, 8))),    # −4: только MCID
          mk(3, visits=((0, 10, 9), (8, 4, 3))),     # −60 %: ответ, MCID, ремиссия
          mk(4, visits=((0, 15, 9),)),               # нет повторного измерения: в знаменателе
          mk(5, visits=((0, None, None), (2, 9, 4)))]  # нет исходного: исключён
    r = response_rates(cs, "gad7")
    assert r["denominator"] == 4
    assert r["response"]["n"] == 2 and r["response"]["pct"] == 50.0
    assert r["mcid"]["n"] == 3
    assert r["remission"]["n"] == 1
    assert r["response"]["ci95"] == wilson(2, 4)


# ---------- Приверженность ----------

def test_adherence_bands_median_unknown():
    cs = [mk(1, intake=(90, 10, 0)), mk(2, intake=(60, 40, 10)), mk(3, intake=(20, 80, 0)),
          mk(4, intake=(0, 0, 5))]
    a = adherence(cs)
    assert a["courses_with_data"] == 3
    assert a["bands"] == {"≥80%": 1, "50–79%": 1, "<50%": 1}
    assert a["median_pct"] == 60.0
    assert a["unknown_share_pct"] == round(100 * 15 / 315, 1)


# ---------- Безопасность ----------

def test_safety_by_term_and_serious():
    cs = [mk(1, aes=[("сонливость", "mild", False), ("головная боль", "moderate", False)]),
          mk(2, aes=[("сонливость", "moderate", False)]),
          mk(3, stop="adverse_event", aes=[("головокружение", "severe", True)]), mk(4)]
    s = safety(cs)
    assert s["with_ae"]["n"] == 3 and s["serious"]["n"] == 1 and s["stopped_due_to_ae"]["n"] == 1
    assert s["by_term"][0] == {"term": "сонливость", "mild": 1, "moderate": 1, "severe": 0, "total": 2}
    assert [r["term"] for r in s["by_term"]] == ["сонливость", "головная боль", "головокружение"]


# ---------- Индекс устойчивой пользы ----------

def test_benefit_index_itt_and_harm_exclusion():
    cs = [mk(1, visits=((0, 16, 9), (8, 6, 4))),                                   # польза
          mk(2, visits=((0, 16, 9), (8, 6, 4)), aes=[("головокружение", "severe", True)]),  # ответ, но серьёзное НЯ
          mk(3, stop="adverse_event", visits=((0, 16, 9), (4, 7, 4))),            # ответ, но отмена из-за НЯ
          mk(4, visits=((0, 16, 9), (8, 14, 8))),                                  # нет ответа
          mk(5, stop="lost_to_followup", visits=((0, 16, 9),))]                    # потерян: без пользы
    b = benefit_index(cs, "gad7")
    assert (b["numerator"], b["denominator"]) == (1, 5)
    assert b["value_pct"] == 20.0 and b["ci95"] == wilson(1, 5)
    assert b["components"] == {"responders": 3, "with_harm": 2}
    assert "все начатые" in b["formula"]


# ---------- Состав выборки ----------

def test_composition_bands():
    cs = [mk(1, age=18), mk(2, age=34, comorbidities=["cardiovascular", "endocrine"]),
          mk(3, age=35, sex="М", concomitant=["antidepressant"]), mk(4, age=65, indication="F43.2")]
    c = composition(cs)
    assert c["age"] == {"18–34": 2, "35–49": 1, "50–64": 0, "65+": 1}
    assert c["sex"] == {"Ж": 3, "М": 1}
    assert c["indication"] == {"F41.1": 3, "F43.2": 1}
    assert c["comorbidity"] == {"none": 3, "cardiovascular": 1, "endocrine": 1}
    assert c["concomitant"] == {"none": 3, "antidepressant": 1}


# ---------- Отчёт и k-анонимность ----------

def test_report_without_k_shows_everything():
    cs = [mk(1), mk(2, stop="switch")]
    r = aviandr_report(cs, {}, "gad7", k_min=1)
    assert r["n"] == 2 and r["suppressed"] is False and r["caveat"] == CAVEAT
    assert r["kpis"]["by_reason"]["switch"] == 1
    for key in ("kpis", "composition", "trajectories", "response", "adherence", "safety", "benefit_index"):
        assert key in r


def test_report_suppressed_below_k():
    r = aviandr_report([mk(i) for i in range(4)], {}, "gad7", k_min=5)
    assert r["suppressed"] is True and r["n"] is None and "5" in r["message"]


def test_report_masks_small_cells_for_researcher():
    cs = [mk(i) for i in range(6)] + [mk(9, stop="switch", aes=[("тошнота", "mild", False)])]
    r = aviandr_report(cs, {}, "gad7", k_min=5)
    assert r["n"] == 7
    assert r["kpis"]["by_reason"]["switch"] is None          # 1 < 5 → скрыто
    assert r["kpis"]["by_reason"]["inefficacy"] == 0          # ноль не раскрывает человека
    assert r["kpis"]["active"] == 6
    assert r["safety"]["with_ae"] == {"n": None, "pct": None, "ci95": None, "hidden": True}
    assert r["safety"]["by_term"][0]["term"] == "тошнота" and r["safety"]["by_term"][0]["total"] is None


def test_report_empty_selection():
    r = aviandr_report([mk(1)], {"sex": "М"}, "gad7", k_min=5)
    assert r["n"] == 0 and r["empty"] is True and r["suppressed"] is False
```

- [ ] **Step 2: Запустить и убедиться, что падает по правильной причине**

Run: `/home/lyssten/projects/Hack-Compass/.ref/venv/bin/python -m pytest tests/test_analytics.py -q`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'kompas_core.analytics'` (и только она).

---

### Task 2: Реализация `kompas_core/analytics.py`

**Files:**
- Create: `kompas_core/analytics.py`
- Modify: `kompas_core/__init__.py`

- [ ] **Step 1: Написать модуль**

```python
"""Аналитика применения препарата по курсам терапии (наблюдательные данные).

Чистые функции без БД и сети. Вход — список курсов (формат в docs/API_CONTRACT.md,
раздел «Курсы для аналитики»). Сервер собирает курсы из своих таблиц, генератор
synthetic/aviandr_cohort.py — из синтетики.

Методологическая оговорка уходит в API и интерфейс: это наблюдение без контрольной группы.
Для исследователя мелкие ячейки (n < k) скрываются — защита от повторной идентификации.
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

from .scales import load_passport

CAVEAT = ("Наблюдение без контрольной группы. Изменение шкалы не отделяет эффект препарата "
          "от естественного течения, регрессии к среднему и отбора пациентов.")

STOP_REASONS = {
    "completed": "Курс завершён",
    "adverse_event": "Нежелательные явления",
    "inefficacy": "Недостаточный эффект",
    "improvement": "Улучшение, отменён досрочно",
    "switch": "Смена препарата",
    "lost_to_followup": "Потеря контакта",
}

OUTCOME_GROUPS = {
    "continued": "Продолжает или завершил курс",
    "stopped_ae": "Отменён из-за НЯ",
    "stopped_inefficacy": "Отменён из-за недостаточного эффекта",
    "stopped_other": "Отменён по другим причинам",
}

WEEKS = tuple(range(0, 13, 2))
AGE_BANDS = ((18, 34, "18–34"), (35, 49, "35–49"), (50, 64, "50–64"), (65, 200, "65+"))

BENEFIT_FORMULA = ("Индекс устойчивой пользы = курсы с ответом (снижение шкалы ≥ 50 % на последнем "
                   "наблюдении), без серьёзных НЯ и без отмены из-за НЯ / все начатые курсы с исходным "
                   "измерением. Курсы без повторного измерения считаются курсами без пользы.")


def outcome_group(course: dict) -> str:
    r = course.get("stop_reason")
    if r in (None, "completed"):
        return "continued"
    if r == "adverse_event":
        return "stopped_ae"
    if r == "inefficacy":
        return "stopped_inefficacy"
    return "stopped_other"


def _match_list(values: list[str], wanted: Optional[str]) -> bool:
    if wanted is None:
        return True
    if wanted == "none":
        return not values
    return wanted in values


def filter_courses(courses: list[dict], f: Optional[dict] = None) -> list[dict]:
    """Фильтры: start_from/start_to (ISO), age_min/age_max, sex, indication, comorbidity,
    concomitant ('none' = нет), doctor_id. Пустые значения и 'all' игнорируются."""
    f = {k: v for k, v in (f or {}).items() if v not in (None, "", "all")}
    out = []
    for c in courses:
        if "start_from" in f and c["start_date"] < f["start_from"]:
            continue
        if "start_to" in f and c["start_date"] > f["start_to"]:
            continue
        if "age_min" in f and c["age"] < int(f["age_min"]):
            continue
        if "age_max" in f and c["age"] > int(f["age_max"]):
            continue
        if "sex" in f and c["sex"] != f["sex"]:
            continue
        if "indication" in f and c["indication"] != f["indication"]:
            continue
        if "doctor_id" in f and c["doctor_id"] != f["doctor_id"]:
            continue
        if not _match_list(c["comorbidities"], f.get("comorbidity")):
            continue
        if not _match_list(c["concomitant"], f.get("concomitant")):
            continue
        out.append(c)
    return out


def kpis(courses: list[dict]) -> dict:
    by_reason = {r: 0 for r in STOP_REASONS if r != "completed"}
    active = completed = 0
    for c in courses:
        r = c.get("stop_reason")
        if r is None:
            active += 1
        elif r == "completed":
            completed += 1
        else:
            by_reason[r] += 1
    return {"assigned": len(courses), "active": active, "completed": completed,
            "discontinued": sum(by_reason.values()), "by_reason": by_reason}


def _value_at(course: dict, scale: str, week: int):
    for v in course["visits"]:
        if v["week"] == week:
            return v.get(scale)
    return None


def _quartiles(xs: list[float]) -> tuple[float, float, float]:
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0], xs[0], xs[0]
    q1, med, q3 = statistics.quantiles(xs, n=4, method="inclusive")
    return q1, med, q3


def _num(x: float):
    """Целые без хвоста .0, остальное — до десятых."""
    x = round(x, 1)
    return int(x) if x == int(x) else x


def trajectories(courses: list[dict], scale: str = "gad7", k_min: int = 1) -> dict:
    out: dict = {}
    for g in OUTCOME_GROUPS:
        members = [c for c in courses if outcome_group(c) == g]
        points = []
        for w in WEEKS:
            xs = [x for c in members if (x := _value_at(c, scale, w)) is not None]
            if not xs:
                continue
            if len(xs) < k_min:
                points.append({"week": w, "n": None, "median": None, "q1": None, "q3": None, "hidden": True})
                continue
            q1, med, q3 = _quartiles(xs)
            points.append({"week": w, "n": len(xs), "median": _num(med), "q1": _num(q1),
                           "q3": _num(q3), "hidden": False})
        out[g] = points
    return out


def wilson(x: int, n: int, z: float = 1.96) -> Optional[list[float]]:
    """95 % доверительный интервал Вильсона для доли x/n."""
    if n == 0:
        return None
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def _rate(x: int, n: int) -> dict:
    return {"n": x, "pct": round(100 * x / n, 1) if n else None, "ci95": wilson(x, n)}


def _baseline_last(course: dict, scale: str):
    """(исходное, последнее после недели 0) или None, если нет исходного измерения."""
    vals = sorted(course["visits"], key=lambda v: v["week"])
    base = next((v.get(scale) for v in vals if v["week"] == 0 and v.get(scale) is not None), None)
    if base is None:
        return None
    later = [v.get(scale) for v in vals if v["week"] > 0 and v.get(scale) is not None]
    return base, (later[-1] if later else None)


def _responded(base: int, last, ch: dict) -> bool:
    return last is not None and base > 0 and (base - last) >= base * ch["response_reduction_fraction"]


def response_rates(courses: list[dict], scale: str = "gad7") -> dict:
    """Доли на последнем наблюдении среди курсов с исходным измерением (ITT)."""
    ch = load_passport(scale)["change"]
    n = resp = mcid = remis = 0
    for c in courses:
        bl = _baseline_last(c, scale)
        if bl is None:
            continue
        n += 1
        base, last = bl
        if last is None:
            continue
        resp += _responded(base, last, ch)
        mcid += (base - last) >= ch["mcid_points"]
        remis += last < ch["remission_below"]
    return {
        "scale": scale, "denominator": n,
        "response": _rate(resp, n), "mcid": _rate(mcid, n), "remission": _rate(remis, n),
        "definitions": {
            "response": f"снижение ≥ {int(ch['response_reduction_fraction'] * 100)} % от исходного",
            "mcid": f"снижение ≥ {ch['mcid_points']} баллов ({ch['mcid_source']})",
            "remission": f"последнее значение < {ch['remission_below']}",
        },
    }


def adherence(courses: list[dict]) -> dict:
    bands = {"≥80%": 0, "50–79%": 0, "<50%": 0}
    pcts: list[float] = []
    taken = missed = unknown = 0
    for c in courses:
        i = c.get("intake") or {}
        t, m, u = i.get("taken", 0), i.get("missed", 0), i.get("unknown", 0)
        taken, missed, unknown = taken + t, missed + m, unknown + u
        if t + m == 0:
            continue
        p = t / (t + m)
        pcts.append(p)
        bands["≥80%" if p >= 0.8 else "50–79%" if p >= 0.5 else "<50%"] += 1
    total = taken + missed + unknown
    return {"courses_with_data": len(pcts),
            "median_pct": round(100 * statistics.median(pcts), 1) if pcts else None,
            "bands": bands,
            "unknown_share_pct": round(100 * unknown / total, 1) if total else None,
            "note": "Отметка не доказывает приём; отсутствие отметки не доказывает пропуск."}


def safety(courses: list[dict]) -> dict:
    by_term: dict[str, dict] = {}
    with_ae = serious = 0
    for c in courses:
        aes = c.get("adverse_events") or []
        with_ae += bool(aes)
        serious += any(e.get("serious") for e in aes)
        for e in aes:
            row = by_term.setdefault(e["term"], {"term": e["term"], "mild": 0, "moderate": 0, "severe": 0, "total": 0})
            row[e["severity"]] += 1
            row["total"] += 1
    n = len(courses)
    stopped = sum(c.get("stop_reason") == "adverse_event" for c in courses)
    return {"courses": n, "with_ae": _rate(with_ae, n), "serious": _rate(serious, n),
            "stopped_due_to_ae": _rate(stopped, n),
            "by_term": sorted(by_term.values(), key=lambda r: (-r["total"], r["term"])),
            "note": "Возникло на фоне лечения ≠ вызвано лечением."}


def benefit_index(courses: list[dict], scale: str = "gad7") -> dict:
    ch = load_passport(scale)["change"]
    n = num = responders = with_harm = 0
    for c in courses:
        bl = _baseline_last(c, scale)
        if bl is None:
            continue
        n += 1
        resp = _responded(*bl, ch)
        harm = (any(e.get("serious") for e in c.get("adverse_events") or [])
                or c.get("stop_reason") == "adverse_event")
        responders += resp
        with_harm += harm
        num += resp and not harm
    r = _rate(num, n)
    return {"scale": scale, "value_pct": r["pct"], "ci95": r["ci95"], "numerator": num,
            "denominator": n, "components": {"responders": responders, "with_harm": with_harm},
            "formula": BENEFIT_FORMULA}


def composition(courses: list[dict]) -> dict:
    out: dict = {"age": {label: 0 for *_, label in AGE_BANDS}, "sex": {}, "indication": {},
                 "comorbidity": {"none": 0}, "concomitant": {"none": 0}}
    for c in courses:
        band = next(label for lo, hi, label in AGE_BANDS if lo <= c["age"] <= hi)
        out["age"][band] += 1
        out["sex"][c["sex"]] = out["sex"].get(c["sex"], 0) + 1
        out["indication"][c["indication"]] = out["indication"].get(c["indication"], 0) + 1
        for key, field in (("comorbidity", "comorbidities"), ("concomitant", "concomitant")):
            for v in c[field] or ["none"]:
                out[key][v] = out[key].get(v, 0) + 1
    return out


def _mask(x, k: int):
    return None if isinstance(x, int) and not isinstance(x, bool) and 0 < x < k else x


def _mask_counts(d: dict, k: int) -> dict:
    return {key: _mask_counts(v, k) if isinstance(v, dict) else _mask(v, k) for key, v in d.items()}


def _mask_rate(r: dict, k: int) -> dict:
    if r["n"] is not None and 0 < r["n"] < k:
        return {"n": None, "pct": None, "ci95": None, "hidden": True}
    return r


def _apply_k(rep: dict, k: int) -> None:
    rep["kpis"] = _mask_counts(rep["kpis"], k)
    rep["composition"] = _mask_counts(rep["composition"], k)
    for key in ("response", "mcid", "remission"):
        rep["response"][key] = _mask_rate(rep["response"][key], k)
    rep["adherence"]["bands"] = _mask_counts(rep["adherence"]["bands"], k)
    for key in ("with_ae", "serious", "stopped_due_to_ae"):
        rep["safety"][key] = _mask_rate(rep["safety"][key], k)
    rep["safety"]["by_term"] = [_mask_counts(r, k) for r in rep["safety"]["by_term"]]
    b = rep["benefit_index"]
    if 0 < b["numerator"] < k:
        b.update(value_pct=None, ci95=None, numerator=None, hidden=True)


def aviandr_report(courses: list[dict], filters: Optional[dict] = None, scale: str = "gad7",
                   k_min: int = 1) -> dict:
    """Полный отчёт для экрана «Авиандр». k_min > 1 — режим исследователя (k-анонимность)."""
    cs = filter_courses(courses, filters)
    base = {"k_min": k_min, "scale": scale, "caveat": CAVEAT}
    if not cs:
        return {**base, "n": 0, "empty": True, "suppressed": False}
    if len(cs) < k_min:
        return {**base, "n": None, "suppressed": True,
                "message": f"В выборке меньше {k_min} курсов — показ скрыт для защиты от повторной идентификации."}
    rep = {**base, "n": len(cs), "empty": False, "suppressed": False,
           "kpis": kpis(cs), "composition": composition(cs),
           "trajectories": trajectories(cs, scale, k_min), "response": response_rates(cs, scale),
           "adherence": adherence(cs), "safety": safety(cs), "benefit_index": benefit_index(cs, scale),
           "labels": {"stop_reasons": STOP_REASONS, "groups": OUTCOME_GROUPS}}
    if k_min > 1:
        _apply_k(rep, k_min)
    return rep
```

- [ ] **Step 2: Экспорт в `kompas_core/__init__.py`**

После строки `from .text_screen import screen_text` добавить:

```python
from .analytics import aviandr_report
```

и в `__all__` добавить `"aviandr_report",` последним элементом.

- [ ] **Step 3: Тесты зелёные**

Run: `/home/lyssten/projects/Hack-Compass/.ref/venv/bin/python -m pytest tests/test_analytics.py -q`
Expected: все тесты PASS. Если падает тест траекторий на квартилях — сверить с `statistics.quantiles([10, 14, 18], n=4, method="inclusive") == [12.0, 14.0, 16.0]`; ожидания теста верны, править реализацию.

- [ ] **Step 4: Весь набор и коммит**

Run: `/home/lyssten/projects/Hack-Compass/.ref/venv/bin/python -m pytest -q` → все PASS (58 старых + новые).

```bash
git add kompas_core/analytics.py kompas_core/__init__.py tests/test_analytics.py
git commit -m "Аналитика применения препарата: KPI, траектории, ответ, приверженность, НЯ, индекс пользы, k-анонимность"
```

---

### Task 3: Тесты генератора когорты (красные)

**Files:**
- Create: `tests/test_aviandr_cohort.py`

- [ ] **Step 1: Написать тесты**

```python
"""Синтетическая когорта курсов Авиандра: соответствие инструкции и пригодность для аналитики."""
from datetime import date, timedelta

import pytest

from kompas_core.analytics import aviandr_report, outcome_group
from synthetic.aviandr_cohort import AE_TERMS, DEMO_DOCTOR, generate_courses

TODAY = date(2026, 10, 26)


@pytest.fixture(scope="module")
def cohort():
    return generate_courses(300, seed=7, today=TODAY)


def test_size_and_determinism(cohort):
    assert len(cohort) == 300
    assert generate_courses(300, seed=7, today=TODAY) == cohort
    assert generate_courses(300, seed=8, today=TODAY) != cohort


def test_registered_conditions(cohort):
    """Взрослые; F43.2 — курс 4–6 недель по инструкции; F41.1 — 8–12 недель (допущение генератора)."""
    assert all(c["age"] >= 18 for c in cohort)
    assert {c["indication"] for c in cohort} == {"F41.1", "F43.2"}
    assert all(c["planned_weeks"] <= 6 for c in cohort if c["indication"] == "F43.2")
    assert all(8 <= c["planned_weeks"] <= 12 for c in cohort if c["indication"] == "F41.1")


def test_adverse_event_terms_from_instruction(cohort):
    aes = [e for c in cohort for e in c["adverse_events"]]
    assert aes, "в когорте должны быть НЯ"
    assert {e["term"] for e in aes} <= set(AE_TERMS)
    assert {e["severity"] for e in aes} <= {"mild", "moderate", "severe"}
    assert all(not e["serious"] or e["severity"] == "severe" for e in aes)


def test_stop_reasons_cover_groups(cohort):
    reasons = {c["stop_reason"] for c in cohort}
    assert {None, "completed", "adverse_event", "inefficacy", "lost_to_followup"} <= reasons
    assert reasons <= {None, "completed", "adverse_event", "inefficacy", "improvement", "switch", "lost_to_followup"}


def test_dates_and_visits_consistent(cohort):
    for c in cohort:
        start = date.fromisoformat(c["start_date"])
        assert start <= TODAY
        weeks = [v["week"] for v in c["visits"]]
        assert weeks[0] == 0 and c["visits"][0]["gad7"] is not None, "исходное измерение есть всегда"
        assert weeks == sorted(weeks) and all(w % 2 == 0 for w in weeks)
        for v in c["visits"]:
            assert v["gad7"] is None or 0 <= v["gad7"] <= 21
            assert v["phq9"] is None or 0 <= v["phq9"] <= 27
        if c["end_date"] is None:
            assert c["stop_reason"] is None
            assert start + timedelta(weeks=max(weeks)) <= TODAY
        else:
            end = date.fromisoformat(c["end_date"])
            assert end <= TODAY and start + timedelta(weeks=max(weeks)) <= end
        assert all(e["week"] <= max(weeks) + 2 for e in c["adverse_events"])


def test_demo_doctor_has_enough_courses(cohort):
    assert sum(c["doctor_id"] == DEMO_DOCTOR for c in cohort) >= 30


def test_report_is_plausible(cohort):
    r = aviandr_report(cohort, {}, "gad7", k_min=5)
    assert r["n"] == 300
    assert 20 <= r["benefit_index"]["value_pct"] <= 80
    cont = [p for p in r["trajectories"]["continued"] if p["week"] == 8][0]
    assert cont["median"] < [p for p in r["trajectories"]["continued"] if p["week"] == 0][0]["median"]
    ineff = [c for c in cohort if outcome_group(c) == "stopped_inefficacy"]
    assert ineff, "должны быть отмены из-за недостаточного эффекта"
```

- [ ] **Step 2: Запустить и убедиться, что падает по правильной причине**

Run: `/home/lyssten/projects/Hack-Compass/.ref/venv/bin/python -m pytest tests/test_aviandr_cohort.py -q`
Expected: `ModuleNotFoundError: No module named 'synthetic.aviandr_cohort'`.

---

### Task 4: Генератор `synthetic/aviandr_cohort.py`

**Files:**
- Create: `synthetic/aviandr_cohort.py`

- [ ] **Step 1: Написать генератор**

```python
"""Синтетическая когорта курсов Авиандра для экрана аналитики применения препарата.

Все численные параметры — допущения генератора, а не данные исследований; на экране
данные помечаются как синтетические. Из инструкции (вторичный источник medi.ru до сверки
с ГРЛС) взяты:
* показания — ГТР (F41.1) и тревожные состояния после COVID-19 при реакции на стресс и
  расстройстве адаптации (F43.2), только взрослые;
* длительность — при ГТР определяет врач (в генераторе 8–12 недель), после COVID-19 —
  4 недели, по решению врача до 6;
* термины нежелательных реакций — раздел «Побочное действие» (часто / нечасто).

Запуск: python synthetic/aviandr_cohort.py → краткая сводка отчёта.
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

TODAY = date(2026, 10, 26)
DEMO_DOCTOR = "doc-ivanova"
DOCTORS = ((DEMO_DOCTOR, 14), ("doc-petrov", 18), ("doc-smirnova", 17),
           ("doc-kuznetsov", 17), ("doc-volkova", 17), ("doc-orlov", 17))

AE_COMMON = ["сонливость", "головная боль", "головокружение", "общая слабость", "парестезии"]
AE_UNCOMMON = ["нарушение сна", "усиление тревоги", "снижение концентрации внимания",
               "нарушение вкуса", "тошнота", "боль в верхней части живота", "запор",
               "повышенная потливость", "мышечная скованность", "боль в спине"]
AE_TERMS = AE_COMMON + AE_UNCOMMON
AE_SOURCE = ("Инструкция Авиандр, раздел «Побочное действие» "
             "(вторичный источник medi.ru; сверить с ГРЛС)")
SEVERITY = ("mild", "moderate", "severe")


def _clip(x: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, x)))


def _adverse_events(rnd: random.Random) -> list[dict]:
    terms = [t for t in AE_COMMON if rnd.random() < 0.06] + [t for t in AE_UNCOMMON if rnd.random() < 0.012]
    out = []
    for t in terms:
        sev = rnd.choices(SEVERITY, (70, 25, 5))[0]
        out.append({"term": t, "severity": sev, "serious": sev == "severe" and rnd.random() < 0.3,
                    "week": rnd.choice((0, 1, 1, 2, 3))})
    return out


def _stop(rnd: random.Random, kind: str, planned: int, aes: list[dict]) -> tuple[int, str]:
    """Неделя и причина окончания курса, если бы он шёл без ограничения датой «сегодня»."""
    worst = max(aes, key=lambda a: SEVERITY.index(a["severity"]), default=None)
    if worst and (worst["severity"] == "severe" or (worst["severity"] == "moderate" and rnd.random() < 0.35)):
        return min(planned, worst["week"] + rnd.choice((1, 2))), "adverse_event"
    if kind == "non" and planned >= 6 and rnd.random() < 0.45:
        return rnd.choice((4, 6)), "inefficacy"
    if rnd.random() < 0.06:
        return rnd.randint(1, planned - 1), "lost_to_followup"
    if rnd.random() < 0.03:
        return rnd.randint(2, planned - 1), "switch"
    if kind == "strong" and planned >= 8 and rnd.random() < 0.08:
        return rnd.choice((4, 6)), "improvement"
    return planned, "completed"


def make_course(i: int, rnd: random.Random, today: date = TODAY) -> dict:
    doctor = rnd.choices([d for d, _ in DOCTORS], [w for _, w in DOCTORS])[0]
    indication = "F41.1" if rnd.random() < 0.8 else "F43.2"
    planned = rnd.choice((8, 10, 12)) if indication == "F41.1" else rnd.choice((4, 4, 6))
    age = rnd.randint(18, 75)
    sex = "Ж" if rnd.random() < 0.65 else "М"
    comorb = []
    if rnd.random() < 0.12 + 0.004 * (age - 18):
        comorb.append("cardiovascular")
    if rnd.random() < 0.12:
        comorb.append("endocrine")
    concom = ["antidepressant"] if rnd.random() < 0.15 else []
    start = today - timedelta(days=rnd.randint(7, 270))

    base_gad = _clip(round(rnd.gauss(14.5, 3)), 10, 21)
    base_phq = _clip(round(0.6 * base_gad + rnd.gauss(0, 3)), 0, 27)
    kind = rnd.choices(("strong", "partial", "non"), (45, 30, 25))[0]
    slope = {"strong": -0.9, "partial": -0.45, "non": -0.1}[kind]

    aes = _adverse_events(rnd)
    stop_week, reason = _stop(rnd, kind, planned, aes)
    end = start + timedelta(weeks=stop_week)
    if end > today:                                   # курс ещё идёт
        reason, end = None, None
        observed = (today - start).days // 7
    else:
        observed = stop_week
    aes = [a for a in aes if a["week"] <= observed]

    visits = []
    for w in range(0, observed + 1, 2):
        if reason == "lost_to_followup" and w >= stop_week:
            break
        if w and rnd.random() < 0.05:
            visits.append({"week": w, "gad7": None, "phq9": None})
            continue
        g = base_gad if w == 0 else _clip(round(base_gad + slope * w + rnd.gauss(0, 1.5)), 0, 21)
        p = base_phq if w == 0 else _clip(round(base_phq + 0.6 * slope * w + rnd.gauss(0, 1.5)), 0, 27)
        visits.append({"week": w, "gad7": g, "phq9": p})

    days = ((end or today) - start).days
    p_take = rnd.choices((0.95, 0.85, 0.7, 0.5), (40, 30, 20, 10))[0]
    p_unknown = rnd.uniform(0.03, 0.15)
    taken = missed = unknown = 0
    for _ in range(days):
        if rnd.random() < p_unknown:
            unknown += 1
        elif rnd.random() < p_take:
            taken += 1
        else:
            missed += 1

    return {
        "course_id": f"AV-{i:04d}", "patient_key": f"AVP-{i:04d}", "doctor_id": doctor,
        "drug_id": "aviandr", "age": age, "sex": sex, "indication": indication,
        "comorbidities": comorb, "concomitant": concom,
        "start_date": start.isoformat(), "end_date": end.isoformat() if end else None,
        "planned_weeks": planned, "stop_reason": reason, "visits": visits,
        "intake": {"taken": taken, "missed": missed, "unknown": unknown},
        "adverse_events": aes, "synthetic": True,
    }


def generate_courses(n: int = 300, seed: int = 7, today: date = TODAY) -> list[dict]:
    rnd = random.Random(seed)
    return [make_course(i, rnd, today) for i in range(n)]


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from kompas_core.analytics import aviandr_report

    rep = aviandr_report(generate_courses(today=date.today()), {}, "gad7", k_min=5)
    print("KPI:", rep["kpis"])
    print("Индекс устойчивой пользы:", rep["benefit_index"]["value_pct"], "%", rep["benefit_index"]["ci95"])
    print("Ответ:", rep["response"]["response"], "Ремиссия:", rep["response"]["remission"])
    print("НЯ:", rep["safety"]["with_ae"], "Серьёзные:", rep["safety"]["serious"])
```

- [ ] **Step 2: Тесты зелёные**

Run: `/home/lyssten/projects/Hack-Compass/.ref/venv/bin/python -m pytest tests/test_aviandr_cohort.py -q`
Expected: все PASS. Если `test_report_is_plausible` падает по индексу пользы вне 20–80 % — вывести значение (`python synthetic/aviandr_cohort.py`) и поправить веса типов ответа `(45, 30, 25)`, не ослабляя тест.

- [ ] **Step 3: Сводка и весь набор**

Run: `/home/lyssten/projects/Hack-Compass/.ref/venv/bin/python synthetic/aviandr_cohort.py` — вывод KPI и индекса без ошибок.
Run: `/home/lyssten/projects/Hack-Compass/.ref/venv/bin/python -m pytest -q` → все PASS.

- [ ] **Step 4: Коммит**

```bash
git add synthetic/aviandr_cohort.py tests/test_aviandr_cohort.py
git commit -m "Синтетическая когорта курсов Авиандра по условиям инструкции"
```

---

### Task 5: Контракт данных

**Files:**
- Modify: `docs/API_CONTRACT.md` — добавить в конец раздел.

- [ ] **Step 1: Дописать раздел**

````markdown
## Курсы для аналитики (`kompas_core.analytics.aviandr_report`)

```python
from kompas_core import aviandr_report
report = aviandr_report(courses, filters={"sex": "Ж", "indication": "F41.1"}, scale="gad7", k_min=5)
```

Курс — словарь: `course_id`, `patient_key`, `doctor_id`, `drug_id`, `age`, `sex` (`Ж|М`),
`indication` (`F41.1|F43.2`), `comorbidities` (`[]` = нет), `concomitant` (`[]` = нет),
`start_date`, `end_date` (`null` = идёт), `planned_weeks`, `stop_reason`
(`null|completed|adverse_event|inefficacy|improvement|switch|lost_to_followup`),
`visits` (`[{week, gad7, phq9}]`, `null` = анкета не пришла), `intake` (`{taken, missed, unknown}`),
`adverse_events` (`[{term, severity: mild|moderate|severe, serious, week}]`).

Фильтры: `start_from`, `start_to`, `age_min`, `age_max`, `sex`, `indication`, `comorbidity`,
`concomitant` (`none` = нет), `doctor_id`. `k_min > 1` — режим исследователя: выборка меньше k
скрывается целиком, ячейки 1…k−1 заменяются на `null`.

Индекс устойчивой пользы = курсы с ответом (снижение ≥ 50 % на последнем наблюдении) без серьёзных
НЯ и без отмены из-за НЯ / все начатые курсы с исходным измерением (ITT), 95 % ДИ Вильсона.
Это описание наблюдения, не оценка эффективности: контрольной группы нет.
````

- [ ] **Step 2: Коммит**

```bash
git add docs/API_CONTRACT.md
git commit -m "Контракт: формат курсов и отчёта аналитики"
```
