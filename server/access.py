"""Права доступа к данным пациента и журнал обращений.

* пациент — только своя карточка;
* врач — пациенты с активной связью, где он лечащий; заместитель — только пациенты, у которых
  есть незакрытый алерт, эскалированный на него (без произвольного расширения доступа);
* исследователь — никогда не открывает карточки, только обезличенную аналитику.
"""
from __future__ import annotations

import sqlite3

from .db import now


def link_kind(conn: sqlite3.Connection, user: dict, pid: str) -> str | None:
    """'lead' | 'deputy' | 'self' | None — на каком основании пользователь видит пациента."""
    if user["role"] == "patient":
        return "self" if user["patient_id"] == pid else None
    if user["role"] != "doctor":
        return None
    if conn.execute("SELECT 1 FROM care_links WHERE patient_id = ? AND doctor_id = ? AND active = 1",
                    (pid, user["id"])).fetchone():
        return "lead"
    if conn.execute("SELECT 1 FROM alerts WHERE patient_id = ? AND assigned_to = ? AND status != 'closed'",
                    (pid, user["id"])).fetchone():
        return "deputy"
    return None


def doctor_patients(conn: sqlite3.Connection, doctor_id: str) -> list[tuple[str, str]]:
    """[(patient_id, 'lead'|'deputy')] — свои активные пациенты и пациенты эскалированных алертов."""
    lead = [r[0] for r in conn.execute("SELECT patient_id FROM care_links WHERE doctor_id = ? AND active = 1 "
                                       "ORDER BY patient_id", (doctor_id,))]
    deputy = [r[0] for r in conn.execute("SELECT DISTINCT patient_id FROM alerts WHERE assigned_to = ? "
                                         "AND status != 'closed' ORDER BY patient_id", (doctor_id,))
              if r[0] not in lead]
    return [(p, "lead") for p in lead] + [(p, "deputy") for p in deputy]


def lead_doctor(conn: sqlite3.Connection, pid: str) -> tuple[str | None, str | None]:
    r = conn.execute("SELECT doctor_id, deputy_id FROM care_links WHERE patient_id = ? AND active = 1",
                     (pid,)).fetchone()
    return (r["doctor_id"], r["deputy_id"]) if r else (None, None)


def audit(conn: sqlite3.Connection, user: dict | None, action: str, pid: str | None, allowed: bool) -> None:
    conn.execute("INSERT INTO audit_log (user_id, role, action, patient_id, allowed, at) VALUES (?, ?, ?, ?, ?, ?)",
                 (user and user["id"], user and user["role"], action, pid, int(allowed), now()))
