"""Курсы терапии из таблиц в формат kompas_core.analytics (см. docs/API_CONTRACT.md).

Аналитика строится из тех же данных, что вводят врач и пациент: анкеты, отметки приёма, НЯ.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date

from kompas_core import score

from .db import loads
from .records import adherence_since

COMORBIDITY_FACTS = {"cardiovascular_disease": "cardiovascular", "endocrine_disorder": "endocrine"}


def _week(days: int) -> int:
    """Номер визита по дням от начала курса: ближайшая чётная неделя, до начала — неделя 0."""
    return 0 if days <= 0 else 2 * int(days / 14 + 0.5)


def build_courses(conn: sqlite3.Connection, drug_id: str, today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = conn.execute(
        "SELECT c.*, p.age, p.sex, p.safety_profile, p.concomitant FROM therapy_courses c "
        "JOIN patients p ON p.id = c.patient_id WHERE c.drug_id = ? ORDER BY c.id", (drug_id,)).fetchall()
    sub = "(SELECT patient_id FROM therapy_courses WHERE drug_id = ?)"
    assess, aes = defaultdict(list), defaultdict(list)
    for a in conn.execute(f"SELECT patient_id, date, scale, answers FROM assessments "
                          f"WHERE patient_id IN {sub} ORDER BY date, id", (drug_id,)):
        assess[a["patient_id"]].append(a)
    for e in conn.execute(f"SELECT * FROM adverse_events WHERE patient_id IN {sub} ORDER BY date, id", (drug_id,)):
        aes[e["patient_id"]].append(e)

    out = []
    for r in rows:
        pid = r["patient_id"]
        start = date.fromisoformat(r["start_date"])
        stop = date.fromisoformat(r["end_date"]) if r["end_date"] else today
        visits: dict[int, dict] = {}
        for a in assess[pid]:
            d = date.fromisoformat(a["date"])
            days = (d - start).days
            week = _week(days)
            if days < -7 or d > stop or week > 12 or a["scale"] not in ("gad7", "phq9"):
                continue
            v = visits.setdefault(week, {"week": week, "gad7": None, "phq9": None})
            v[a["scale"]] = score(a["scale"], loads(a["answers"])).total
        events = []
        for e in aes[pid]:
            d = date.fromisoformat(e["date"])
            if start <= d <= stop:
                events.append({"term": e["description"], "severity": e["severity"],
                               "serious": bool(e["serious"]), "week": (d - start).days // 7})
        safety = loads(r["safety_profile"]) or {}
        out.append({
            "course_id": r["id"], "patient_key": pid, "doctor_id": r["prescribed_by"],
            "drug_id": r["drug_id"], "age": r["age"], "sex": r["sex"],
            "indication": r["indication_code"],
            "comorbidities": [v for k, v in COMORBIDITY_FACTS.items() if safety.get(k) is True],
            "concomitant": loads(r["concomitant"]) or [],
            "start_date": r["start_date"], "end_date": r["end_date"],
            "planned_weeks": r["planned_weeks"], "stop_reason": r["stop_reason"],
            "visits": [visits[w] for w in sorted(visits)],
            "intake": adherence_since(conn, pid, start, stop),
            "adverse_events": events,
        })
    return out
