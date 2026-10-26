"""Демо-данные: врачи, исследователь, сценарные пациенты (synthetic/demo_patients.py) и
синтетическая когорта курсов Авиандра (synthetic/aviandr_cohort.py). Пароль у всех — «demo».
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

from synthetic.demo_patients import PATIENTS, SAFE, _spread

from .auth import hash_password
from .db import dumps, tx

DEMO_PASSWORD = "demo"
LEAD_DOCTOR, DEPUTY = "doc-ivanova", "doc-petrov"
DOCTORS = [
    (LEAD_DOCTOR, "ivanova", "Иванова Елена Андреевна, терапевт"),
    (DEPUTY, "petrov", "Петров Сергей Викторович, терапевт (заместитель)"),
    ("doc-smirnova", "smirnova", "Смирнова О. П., терапевт"),
    ("doc-kuznetsov", "kuznetsov", "Кузнецов А. Н., терапевт"),
    ("doc-volkova", "volkova", "Волкова Т. С., терапевт"),
    ("doc-orlov", "orlov", "Орлов Д. М., терапевт"),
]
RESEARCHER = ("res-1", "researcher", "Исследователь (обезличенные данные)")
PATIENT_LOGINS = {"P-001": "anna", "P-002": "sergey", "P-003": "olga", "P-004": "igor",
                  "P-005": "maria", "P-006": "dmitry", "P-007": "elena", "P-008": "alexey"}
INDICATION_LABELS = {"F41.1": "Генерализованное тревожное расстройство",
                     "F43.2": "Расстройство адаптации, тревожное состояние после COVID-19"}


def _insert_patient(conn: sqlite3.Connection, **f) -> None:
    for k in ("diagnoses", "safety_profile", "symptom_checklist", "context", "concomitant"):
        if k in f:
            f[k] = dumps(f[k])
    cols = ", ".join(f)
    conn.execute(f"INSERT INTO patients ({cols}) VALUES ({', '.join('?' * len(f))})", tuple(f.values()))


def _intake_marks(conn, pid: str, start: date, statuses: list) -> None:
    conn.executemany("INSERT INTO intake_marks (patient_id, date, status) VALUES (?, ?, ?)",
                     [(pid, (start + timedelta(days=i)).isoformat(), s) for i, s in enumerate(statuses) if s])


def insert_scenario_patient(conn: sqlite3.Connection, p: dict, today: date) -> None:
    pid = p["patient_id"]
    _insert_patient(conn, id=pid, name=p["name"], age=p["age"], sex=p["sex"], primary_scale=p["primary_scale"],
                    diagnoses=p["diagnoses"], safety_profile=p["safety_profile"],
                    symptom_checklist=p["symptom_checklist"], context=p.get("context") or {},
                    expected_interval_days=p["expected_interval_days"],
                    missed_consecutive=p["selfreports_missed_consecutive"],
                    emergency_active=int(bool(p["emergency_button"])), scenario=p["scenario"])
    conn.execute("INSERT INTO care_links (patient_id, doctor_id, deputy_id) VALUES (?, ?, ?)", (pid, LEAD_DOCTOR, DEPUTY))
    conn.executemany("INSERT INTO assessments (patient_id, date, scale, answers) VALUES (?, ?, ?, ?)",
                     [(pid, a["date"], a["scale"], dumps(a["answers"])) for a in p["assessments"]])
    conn.executemany("INSERT INTO diary (patient_id, date, text) VALUES (?, ?, ?)",
                     [(pid, d["date"], d["text"]) for d in p["diary"]])
    conn.executemany("INSERT INTO adverse_events (patient_id, date, description, serious, is_new) VALUES (?, ?, ?, ?, ?)",
                     [(pid, e["date"], e["description"], int(e["serious"]), int(e.get("new", True)))
                      for e in p["adverse_events"]])
    indication = next((d["code"] for d in p["diagnoses"] if d["status"] == "confirmed"), None)
    for i, t in enumerate(p["therapy"]["current"]):
        conn.execute("INSERT INTO therapy_courses (id, patient_id, drug_id, mnn, indication_code, start_date, "
                     "planned_weeks, prescribed_by) VALUES (?, ?, ?, ?, ?, ?, 8, ?)",
                     (f"{pid}-T{i + 1}", pid, "aviandr" if "Авиандр" in t["mnn"] else None,
                      t["mnn"], indication, t["start_date"], LEAD_DOCTOR))
    adh = p.get("adherence")
    if adh and p["therapy"]["current"]:
        # В демо-профиле — доли; переводим в ежедневные отметки за время курса
        start = date.fromisoformat(p["therapy"]["current"][-1]["start_date"])
        days = (today - start).days
        total = adh["confirmed"] + adh["missed"] + adh["unknown"]
        n_missed = max(1, round(days * adh["missed"] / total)) if adh["missed"] else 0
        n_taken = round(days * adh["confirmed"] / total)
        statuses = ["taken"] * n_taken + ["missed"] * n_missed + [None] * (days - n_taken - n_missed)
        random.Random(pid).shuffle(statuses)
        _intake_marks(conn, pid, start, statuses)


def insert_course(conn: sqlite3.Connection, c: dict) -> None:
    """Курс из synthetic/aviandr_cohort.py → пациент, связь с врачом, анкеты, отметки, НЯ."""
    pid, start = c["patient_key"], date.fromisoformat(c["start_date"])
    safety = {**SAFE, "cardiovascular_disease": "cardiovascular" in c["comorbidities"],
              "endocrine_disorder": "endocrine" in c["comorbidities"]}
    _insert_patient(conn, id=pid, name=f"Пациент {pid} (синт.)", age=c["age"], sex=c["sex"], primary_scale="gad7",
                    diagnoses=[{"code": c["indication"], "status": "confirmed",
                                "label": INDICATION_LABELS.get(c["indication"], c["indication"])}],
                    safety_profile=safety, symptom_checklist={"mania_or_psychosis": False},
                    concomitant=c["concomitant"], scenario="Когорта наблюдения Авиандра (синтетика)")
    conn.execute("INSERT INTO care_links (patient_id, doctor_id, deputy_id, active) VALUES (?, ?, ?, ?)",
                 (pid, c["doctor_id"], DEPUTY if c["doctor_id"] == LEAD_DOCTOR else None,
                  int(c["end_date"] is None)))
    conn.execute("INSERT INTO therapy_courses (id, patient_id, drug_id, mnn, indication_code, start_date, end_date, "
                 "planned_weeks, stop_reason, prescribed_by) VALUES (?, ?, 'aviandr', 'Авиандр', ?, ?, ?, ?, ?, ?)",
                 (c["course_id"], pid, c["indication"], c["start_date"], c["end_date"], c["planned_weeks"],
                  c["stop_reason"], c["doctor_id"]))
    rows = []
    for v in c["visits"]:
        d = (start + timedelta(days=7 * v["week"] - (1 if v["week"] == 0 else 0))).isoformat()
        if v["gad7"] is not None:
            rows.append((pid, d, "gad7", dumps(_spread(v["gad7"], 7))))
        if v["phq9"] is not None:
            rows.append((pid, d, "phq9", dumps(_spread(min(v["phq9"], 24), 8) + [0])))
    conn.executemany("INSERT INTO assessments (patient_id, date, scale, answers) VALUES (?, ?, ?, ?)", rows)
    i = c["intake"]
    statuses = ["taken"] * i["taken"] + ["missed"] * i["missed"] + [None] * i["unknown"]
    random.Random(c["course_id"]).shuffle(statuses)
    _intake_marks(conn, pid, start, statuses)
    conn.executemany("INSERT INTO adverse_events (patient_id, date, description, severity, serious, is_new) "
                     "VALUES (?, ?, ?, ?, ?, 0)",
                     [(pid, (start + timedelta(weeks=e["week"])).isoformat(), e["term"], e["severity"],
                       int(e["serious"])) for e in c["adverse_events"]])


def seed_demo(conn: sqlite3.Connection, courses: list[dict] | None = None, today: date | None = None) -> None:
    today = today or date.today()
    if courses is None:
        from synthetic.aviandr_cohort import generate_courses
        courses = generate_courses(today=today)
    pwd = hash_password(DEMO_PASSWORD)
    with tx(conn):
        for uid, login, name in DOCTORS:
            conn.execute("INSERT INTO users (id, login, pwd_hash, role, display_name) VALUES (?, ?, ?, 'doctor', ?)",
                         (uid, login, pwd, name))
        conn.execute("INSERT INTO users (id, login, pwd_hash, role, display_name) VALUES (?, ?, ?, 'researcher', ?)",
                     (RESEARCHER[0], RESEARCHER[1], pwd, RESEARCHER[2]))
        for p in PATIENTS:
            insert_scenario_patient(conn, p, today)
            conn.execute("INSERT INTO users (id, login, pwd_hash, role, display_name, patient_id) "
                         "VALUES (?, ?, ?, 'patient', ?, ?)",
                         (f"pat-{p['patient_id']}", PATIENT_LOGINS[p["patient_id"]], pwd,
                          p["name"].replace(" (синт.)", ""), p["patient_id"]))
        for c in courses:
            insert_course(conn, c)
