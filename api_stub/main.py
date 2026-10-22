"""Минимальный эталонный API поверх kompas_core — для демо фронтенда и как образец для бэкенда.

Это НЕ продуктовый сервер: нет авторизации, БД и аудита (это зона роли 3).
Хранит состояние в памяти. Запуск:
    uvicorn api_stub.main:app --reload --port 8000

Контракт эндпоинтов описан в docs/API_CONTRACT.md.
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kompas_core import evaluate_patient, ENGINE_VERSION  # noqa: E402
from kompas_core.scales import ScaleInputError  # noqa: E402
from synthetic.demo_patients import PATIENTS  # noqa: E402

app = FastAPI(title="Компас — API-заглушка", version=ENGINE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DB: dict[str, dict] = {p["patient_id"]: copy.deepcopy(p) for p in PATIENTS}
DECISIONS: list[dict] = []          # журнал решений врача
ALERT_LOG: list[dict] = []          # жизненный цикл алертов


def _now():
    return datetime.now(timezone.utc).isoformat()


def _evaluate(pid: str) -> dict:
    t0 = time.perf_counter()
    ev = evaluate_patient(DB[pid], drugs=["aviandr"])
    ev["api_elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return ev


@app.get("/patients")
def list_patients():
    out = []
    for pid, rec in DB.items():
        ev = _evaluate(pid)
        out.append({"record": rec, "evaluation": ev})
    return out


@app.get("/patients/{pid}")
def get_patient(pid: str):
    if pid not in DB:
        raise HTTPException(404)
    return {"record": DB[pid], "evaluation": _evaluate(pid),
            "decisions": [d for d in DECISIONS if d["patient_id"] == pid]}


class Questionnaire(BaseModel):
    scale: str = Field(pattern="^(phq9|gad7)$")
    answers: list[int | None]
    date: str | None = None


class SelfReport(BaseModel):
    questionnaires: list[Questionnaire] = []
    diary_text: str | None = None
    medication_taken: str | None = Field(default=None, pattern="^(taken|missed|unknown)$")
    adverse_event: str | None = None
    adverse_event_serious: bool = False
    emergency: bool = False


@app.post("/patients/{pid}/self-report")
def submit_self_report(pid: str, body: SelfReport):
    """Пациент отправляет самоотчёт → данные сохраняются → правила → алерт врачу.

    Метки времени для метрики «время доставки алерта»: saved_at → alert_created_at.
    """
    if pid not in DB:
        raise HTTPException(404)
    rec = DB[pid]
    saved_at = _now()
    d = date.today().isoformat()
    for q in body.questionnaires:
        try:
            from kompas_core import score
            score(q.scale, q.answers)          # валидация до записи
        except ScaleInputError as e:
            raise HTTPException(422, str(e))
        rec["assessments"].append({"date": q.date or d, "scale": q.scale, "answers": q.answers})
    if body.questionnaires:
        rec["selfreports_missed_consecutive"] = 0
    if body.diary_text:
        rec["diary"].append({"date": d, "text": body.diary_text})
    if body.adverse_event:
        rec["adverse_events"].append({"date": d, "description": body.adverse_event,
                                      "serious": body.adverse_event_serious, "new": True})
    if body.emergency:
        rec["emergency_button"] = True
    if body.medication_taken:
        a = rec.get("adherence") or {"confirmed": 0, "missed": 0, "unknown": 0}
        a[{"taken": "confirmed", "missed": "missed", "unknown": "unknown"}[body.medication_taken]] += 1
        rec["adherence"] = a

    ev = _evaluate(pid)
    created = _now()
    for f in ev["findings"]:
        if f["kind"] == "alert":
            ALERT_LOG.append({"alert_id": str(uuid.uuid4()), "patient_id": pid, "rule_id": f["rule_id"],
                              "priority": f["priority"], "saved_at": saved_at, "created_at": created,
                              "status": "created", "history": [{"status": "created", "at": created}]})
    patient_messages = [f["patient_message"] for f in ev["findings"] if f.get("patient_message")]
    return {"saved_at": saved_at, "evaluation": ev, "patient_messages": patient_messages}


class Decision(BaseModel):
    finding_rule_id: str
    action: str = Field(pattern="^(confirm|reject|modify)$")
    comment: str | None = None
    doctor_id: str = "doctor-demo"


@app.post("/patients/{pid}/decisions")
def record_decision(pid: str, body: Decision):
    """Журнал решений: каждое предложение системы подтверждает/отклоняет/меняет врач."""
    if body.action in ("reject", "modify") and not body.comment:
        raise HTTPException(422, "Для отклонения или изменения нужна причина")
    ev = _evaluate(pid)
    f = next((x for x in ev["findings"] if x["rule_id"] == body.finding_rule_id), None)
    entry = {"patient_id": pid, **body.model_dump(), "at": _now(),
             "rule_version": f["rule_version"] if f else None, "engine_version": ENGINE_VERSION,
             "evidence_snapshot": f["evidence"] if f else None}
    DECISIONS.append(entry)
    for a in ALERT_LOG:
        if a["patient_id"] == pid and a["rule_id"] == body.finding_rule_id and a["status"] != "closed":
            a["status"] = "closed"
            a["history"].append({"status": "closed", "at": entry["at"], "action": body.action})
    return entry


@app.get("/alerts")
def alerts():
    return ALERT_LOG


@app.post("/demo/reset")
def reset():
    DB.clear()
    DB.update({p["patient_id"]: copy.deepcopy(p) for p in PATIENTS})
    DECISIONS.clear()
    ALERT_LOG.clear()
    return {"ok": True}
