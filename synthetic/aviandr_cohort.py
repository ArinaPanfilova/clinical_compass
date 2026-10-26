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
    kind = rnd.choices(("strong", "partial", "non"), (60, 25, 15))[0]
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
