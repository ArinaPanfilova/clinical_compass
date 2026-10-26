"""Сборка записи пациента из таблиц в формат контракта ядра (docs/API_CONTRACT.md)."""
from __future__ import annotations

import sqlite3
from datetime import date

from .db import loads


def adherence_since(conn: sqlite3.Connection, pid: str, start: date, stop: date) -> dict:
    """Подтверждённые приёмы, подтверждённые пропуски и дни без отметки за [start, stop)."""
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM intake_marks WHERE patient_id = ? AND date >= ? AND date < ? "
        "GROUP BY status", (pid, start.isoformat(), stop.isoformat())).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    taken, missed = counts.get("taken", 0), counts.get("missed", 0)
    return {"taken": taken, "missed": missed, "unknown": max(0, (stop - start).days - taken - missed)}


def build_record(conn: sqlite3.Connection, pid: str, today: date | None = None) -> dict:
    p = conn.execute("SELECT * FROM patients WHERE id = ?", (pid,)).fetchone()
    if p is None:
        raise KeyError(pid)
    today = today or date.today()

    assessments = [{"date": r["date"], "scale": r["scale"], "answers": loads(r["answers"])}
                   for r in conn.execute("SELECT date, scale, answers FROM assessments "
                                         "WHERE patient_id = ? ORDER BY date, id", (pid,))]
    diary = [{"date": r["date"], "text": r["text"]}
             for r in conn.execute("SELECT date, text FROM diary WHERE patient_id = ? ORDER BY date, id", (pid,))]
    aes = [{"id": r["id"], "date": r["date"], "description": r["description"], "severity": r["severity"],
            "serious": bool(r["serious"]), "new": bool(r["is_new"])}
           for r in conn.execute("SELECT * FROM adverse_events WHERE patient_id = ? ORDER BY date, id", (pid,))]
    courses = conn.execute("SELECT * FROM therapy_courses WHERE patient_id = ? AND end_date IS NULL "
                           "ORDER BY start_date", (pid,)).fetchall()

    therapy = {"current": [{"mnn": c["mnn"], "start_date": c["start_date"], "drug_id": c["drug_id"]}
                           for c in courses], "weeks_on_current": None}
    adherence = None
    if courses:
        start = date.fromisoformat(courses[-1]["start_date"])
        therapy["weeks_on_current"] = (today - start).days // 7
        a = adherence_since(conn, pid, start, today)
        if a["taken"] or a["missed"]:
            adherence = {"confirmed": a["taken"], "missed": a["missed"], "unknown": a["unknown"]}

    return {
        "patient_id": p["id"], "name": p["name"], "age": p["age"], "sex": p["sex"],
        "primary_scale": p["primary_scale"], "diagnoses": loads(p["diagnoses"]),
        "assessments": assessments, "expected_interval_days": p["expected_interval_days"],
        "selfreports_missed_consecutive": p["missed_consecutive"],
        "diary": diary, "adverse_events": aes,
        "emergency_button": bool(p["emergency_active"]),
        "symptom_checklist": loads(p["symptom_checklist"]),
        "therapy": therapy, "safety_profile": loads(p["safety_profile"]),
        "context": loads(p["context"]), "adherence": adherence, "scenario": p["scenario"],
    }
