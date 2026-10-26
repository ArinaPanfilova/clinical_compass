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
