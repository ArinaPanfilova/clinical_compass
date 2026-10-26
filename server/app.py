"""HTTP-сервер «Компаса»: роли, карточки пациентов, самоотчёты, алерты, сообщения, аналитика.

API — под префиксом /api; собранный фронтенд (frontend/dist), если есть, раздаётся с «/».
Клиническая логика — только в kompas_core; сервер хранит данные, проверяет права и доставляет алерты.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kompas_core import ENGINE_VERSION, aviandr_report, evaluate_patient, extract, load_card, score
from kompas_core.scales import ScaleInputError

from . import access, alerts
from .consent import CONSENT, VERSION as CONSENT_VERSION
from .auth import make_token, read_token, verify_password
from .courses import build_courses
from .db import connect, dumps, init_schema, loads, now, tx
from .records import build_record
from .seed import seed_demo

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
POLL_S = 0.5          # как часто поток событий проверяет БД: алерты из других процессов и после перезапуска
log = logging.getLogger("kompas")


def prepare_db(db_path: str | Path, seed_courses: list[dict] | None = None) -> None:
    """Схема и демо-данные при первом запуске. При нескольких воркерах вызывается один раз в главном процессе."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        init_schema(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed_demo(conn, courses=seed_courses)
    finally:
        conn.close()


class Login(BaseModel):
    login: str
    password: str


class Questionnaire(BaseModel):
    scale: str = Field(pattern="^(phq9|gad7)$")
    answers: list[int | None]


class SelfReport(BaseModel):
    questionnaires: list[Questionnaire] = []
    diary_text: str | None = Field(default=None, max_length=4000)
    medication_taken: Literal["taken", "missed"] | None = None
    missed_reason: str | None = Field(default=None, max_length=500)
    adverse_event: str | None = Field(default=None, max_length=1000)
    adverse_event_serious: bool = False
    emergency: bool = False


class Decision(BaseModel):
    finding_rule_id: str
    action: Literal["confirm", "reject", "modify"]
    comment: str | None = Field(default=None, max_length=2000)


class MessageIn(BaseModel):
    text: str = Field(max_length=4000)


class Intake(BaseModel):
    status: Literal["taken", "missed"]
    reason: str | None = Field(default=None, max_length=500)


class ReferralIn(BaseModel):
    necessity: Literal["mandatory", "desirable"]
    urgency: Literal["emergency", "urgent", "planned"]
    reason: str = Field(max_length=2000)
    rule_id: str | None = None


class ReferralStatus(BaseModel):
    status: Literal["issued", "scheduled", "completed", "cancelled"]
    note: str | None = Field(default=None, max_length=1000)


class ConsentIn(BaseModel):
    version: str


class DocumentIn(BaseModel):
    text: str = Field(max_length=60_000)


class SafetyFacts(BaseModel):
    facts: dict[str, bool | None]
    source: Literal["document", "manual"]
    document_id: int | None = None


def _safety_keys() -> set[str]:
    """Факты профиля безопасности — те, что проверяет карточка препарата."""
    card = load_card("aviandr")
    return {x["fact"].removeprefix("safety.") for x in card["contraindications"] + card["cautions"]}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _public_user(u) -> dict:
    return {"id": u["id"], "role": u["role"], "display_name": u["display_name"], "patient_id": u["patient_id"]}


def evaluate(record: dict) -> dict:
    t0 = time.perf_counter()
    ev = evaluate_patient(record, drugs=["aviandr"])
    ev["api_elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return ev


def create_app(db_path: str | Path, secret: str = "dev-secret-change-me", escalate_after_s: float = 60,
               demo: bool = True, seed_courses: list[dict] | None = None, start_background: bool = True) -> FastAPI:
    db_path = Path(db_path)
    prepare_db(db_path, seed_courses)
    broker = alerts.Broker()

    def run_escalation() -> list[dict]:
        conn = connect(db_path)
        try:
            if not alerts.has_escalation_candidates(conn):     # без блокировки записи, если делать нечего
                return []
            with tx(conn):
                return alerts.escalate_due(conn, datetime.now(timezone.utc), escalate_after_s)
        finally:
            conn.close()

    async def escalation_loop() -> None:
        while True:
            await asyncio.sleep(1)
            try:
                for a in await asyncio.to_thread(run_escalation):
                    broker.publish(a["assigned_to"], {"type": "alert", "data": a})
                    lead, _ = access.lead_doctor(connect(db_path), a["patient_id"])
                    if lead:
                        broker.publish(lead, {"type": "alert_update", "data": a})
            except Exception:                       # цикл эскалации не должен умирать
                log.exception("escalation loop")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        broker.bind(asyncio.get_running_loop())
        task = asyncio.create_task(escalation_loop()) if start_background else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Компас API", version=ENGINE_VERSION, lifespan=lifespan)
    api = APIRouter(prefix="/api")

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def user_from_token(conn: sqlite3.Connection, token: str | None) -> dict:
        uid = read_token(token or "", secret)
        row = uid and conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not row:
            raise HTTPException(401, "Требуется вход")
        return dict(row)

    def current_user(conn: sqlite3.Connection = Depends(get_conn),
                     authorization: str | None = Header(default=None)) -> dict:
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
        return user_from_token(conn, token)

    def require_patient_access(conn: sqlite3.Connection, user: dict, pid: str, action: str) -> str:
        kind = access.link_kind(conn, user, pid)
        access.audit(conn, user, action, pid, kind is not None)
        if kind is None:
            raise HTTPException(403, "Нет доступа к данным этого пациента")
        return kind

    def decisions_for(conn: sqlite3.Connection, pid: str) -> list[dict]:
        return [{**dict(r), "finding_rule_id": r["rule_id"], "evidence": loads(r["evidence"])}
                for r in conn.execute("SELECT * FROM decisions WHERE patient_id = ? ORDER BY id", (pid,))]

    def bundle(conn: sqlite3.Connection, pid: str, link: str) -> dict:
        """Карточка: запись, оценка ядра; для врача — ещё алерты пациента и журнал решений."""
        record = build_record(conn, pid)
        doctor = link in ("lead", "deputy")
        pa = [alerts.get_alert(conn, r[0]) for r in conn.execute(
            "SELECT id FROM alerts WHERE patient_id = ? ORDER BY created_at", (pid,))] if doctor else []
        refs = [dict(r) for r in conn.execute("SELECT * FROM referrals WHERE patient_id = ? ORDER BY id", (pid,))]
        return {"record": record, "evaluation": evaluate(record), "link": link, "alerts": pa,
                "decisions": decisions_for(conn, pid) if doctor else [], "referrals": refs}

    @api.get("/health")
    def health(conn: sqlite3.Connection = Depends(get_conn)):
        conn.execute("SELECT 1").fetchone()
        return {"ok": True, "engine_version": ENGINE_VERSION}

    @api.post("/auth/login")
    def login(body: Login, conn: sqlite3.Connection = Depends(get_conn)):
        u = conn.execute("SELECT * FROM users WHERE login = ?", (body.login,)).fetchone()
        if not u or not verify_password(body.password, u["pwd_hash"]):
            access.audit(conn, None, f"login_failed:{body.login}", None, False)
            raise HTTPException(401, "Неверный логин или пароль")
        access.audit(conn, dict(u), "login", None, True)
        return {"token": make_token(u["id"], secret), "user": _public_user(u)}

    def has_consent(conn: sqlite3.Connection, pid: str) -> bool:
        return conn.execute("SELECT 1 FROM consents WHERE patient_id = ? AND version = ?",
                            (pid, CONSENT_VERSION)).fetchone() is not None

    def require_consent(conn: sqlite3.Connection, user: dict, pid: str, action: str) -> None:
        if user["role"] == "patient" and not has_consent(conn, pid):
            access.audit(conn, user, f"{action}:no_consent", pid, False)
            raise HTTPException(403, "Нужно согласие на обработку данных")

    @api.get("/me")
    def me(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        required = user["role"] == "patient" and not has_consent(conn, user["patient_id"])
        return {**_public_user(user), "consent_required": required, "consent": CONSENT if required else None}

    @api.post("/consent")
    def accept_consent(body: ConsentIn, user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        if user["role"] != "patient":
            raise HTTPException(403, "Согласие даёт пациент")
        if body.version != CONSENT_VERSION:
            raise HTTPException(422, "Устаревшая версия текста согласия")
        with tx(conn):
            conn.execute("INSERT OR IGNORE INTO consents (patient_id, version, accepted_at, user_id) VALUES (?, ?, ?, ?)",
                         (user["patient_id"], CONSENT_VERSION, now(), user["id"]))
            access.audit(conn, user, "consent_accepted", user["patient_id"], True)
        return {"ok": True, "version": CONSENT_VERSION}

    @api.get("/patients")
    def list_patients(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        if user["role"] != "doctor":
            access.audit(conn, user, "list_patients", None, False)
            raise HTTPException(403, "Список пациентов доступен только врачу")
        access.audit(conn, user, "list_patients", None, True)
        return [bundle(conn, pid, link) for pid, link in access.doctor_patients(conn, user["id"])]

    @api.get("/patients/{pid}")
    def get_patient(pid: str, user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        link = require_patient_access(conn, user, pid, "view_patient")
        return bundle(conn, pid, link)

    def require_doctor(conn: sqlite3.Connection, user: dict, action: str, pid: str | None = None) -> None:
        if user["role"] != "doctor":
            access.audit(conn, user, action, pid, False)
            raise HTTPException(403, "Действие доступно только врачу")

    @api.post("/patients/{pid}/self-report")
    def self_report(pid: str, body: SelfReport, user: dict = Depends(current_user),
                    conn: sqlite3.Connection = Depends(get_conn),
                    idempotency_key: str | None = Header(default=None)):
        """Данные пациента и алерты сохраняются одной транзакцией; повтор с тем же ключом ничего не меняет."""
        if user["role"] != "patient":
            access.audit(conn, user, "self_report", pid, False)
            raise HTTPException(403, "Самоотчёт отправляет только пациент")
        require_patient_access(conn, user, pid, "self_report")
        emergency_only = body.emergency and not (body.questionnaires or body.diary_text or body.adverse_event
                                                 or body.medication_taken)
        if not emergency_only:              # экстренное обращение — без согласия (защита жизни и здоровья)
            require_consent(conn, user, pid, "self_report")
        for q in body.questionnaires:
            try:
                score(q.scale, q.answers)          # проверка до записи
            except ScaleInputError as e:
                raise HTTPException(422, str(e))
        created: list[dict] = []
        with tx(conn, durable=True):
            if idempotency_key:
                row = conn.execute("SELECT response FROM self_reports WHERE idempotency_key = ? AND patient_id = ?",
                                   (idempotency_key, pid)).fetchone()
                if row:
                    return loads(row["response"])
            saved_at, today = now(), date.today().isoformat()
            conn.executemany("INSERT INTO assessments (patient_id, date, scale, answers, submitted_at) "
                             "VALUES (?, ?, ?, ?, ?)",
                             [(pid, today, q.scale, dumps(q.answers), saved_at) for q in body.questionnaires])
            if body.questionnaires:
                conn.execute("UPDATE patients SET missed_consecutive = 0 WHERE id = ?", (pid,))
            if body.diary_text and body.diary_text.strip():
                conn.execute("INSERT INTO diary (patient_id, date, text, submitted_at) VALUES (?, ?, ?, ?)",
                             (pid, today, body.diary_text.strip(), saved_at))
            if body.adverse_event and body.adverse_event.strip():
                conn.execute("INSERT INTO adverse_events (patient_id, date, description, serious, submitted_at) "
                             "VALUES (?, ?, ?, ?, ?)", (pid, today, body.adverse_event.strip(),
                                                        int(body.adverse_event_serious), saved_at))
            if body.medication_taken:
                conn.execute("INSERT OR REPLACE INTO intake_marks (patient_id, date, status, reason) VALUES (?, ?, ?, ?)",
                             (pid, today, body.medication_taken, body.missed_reason))
            if body.emergency:
                conn.execute("UPDATE patients SET emergency_active = 1 WHERE id = ?", (pid,))
            ev = evaluate(build_record(conn, pid))
            created = alerts.create_alerts(conn, pid, ev, saved_at)
            resp = {"saved_at": saved_at, "evaluation": ev, "alerts_created": [a["id"] for a in created],
                    "patient_messages": [f["patient_message"] for f in ev["findings"] if f.get("patient_message")]}
            if idempotency_key:
                conn.execute("INSERT INTO self_reports (idempotency_key, patient_id, received_at, response) "
                             "VALUES (?, ?, ?, ?)", (idempotency_key, pid, saved_at, dumps(resp)))
        for a in created:
            broker.publish(a["assigned_to"], {"type": "alert", "data": a})
        return resp

    @api.post("/patients/{pid}/decisions")
    def record_decision(pid: str, body: Decision, user: dict = Depends(current_user),
                        conn: sqlite3.Connection = Depends(get_conn)):
        """Каждое предложение системы врач подтверждает, отклоняет или меняет — с причиной."""
        require_doctor(conn, user, "decision", pid)
        require_patient_access(conn, user, pid, "decision")
        if body.action in ("reject", "modify") and not (body.comment and body.comment.strip()):
            raise HTTPException(422, "Для отклонения или изменения нужна причина")
        with tx(conn):
            ev = evaluate(build_record(conn, pid))
            f = next((x for x in ev["findings"] if x["rule_id"] == body.finding_rule_id), None)
            entry = {"patient_id": pid, "doctor_id": user["id"], "finding_rule_id": body.finding_rule_id,
                     "action": body.action, "comment": body.comment, "at": now(),
                     "rule_version": f["rule_version"] if f else None, "engine_version": ENGINE_VERSION,
                     "evidence_snapshot": f["evidence"] if f else None}
            conn.execute("INSERT INTO decisions (patient_id, doctor_id, rule_id, rule_version, engine_version, action, "
                         "comment, evidence, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (pid, user["id"], body.finding_rule_id, entry["rule_version"], ENGINE_VERSION,
                          body.action, body.comment, dumps(entry["evidence_snapshot"]), entry["at"]))
            alerts.close_for_decision(conn, pid, body.finding_rule_id, user["id"], body.action)
        return entry

    @api.get("/patients/{pid}/decisions")
    def list_decisions(pid: str, user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        require_doctor(conn, user, "list_decisions", pid)
        require_patient_access(conn, user, pid, "list_decisions")
        return decisions_for(conn, pid)

    @api.get("/alerts")
    def list_alerts(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        require_doctor(conn, user, "list_alerts")
        return alerts.alerts_for(conn, user["id"])

    @api.post("/alerts/{aid}/{action}")
    def alert_action(aid: str, action: Literal["ack", "accept", "close"], user: dict = Depends(current_user),
                     conn: sqlite3.Connection = Depends(get_conn)):
        require_doctor(conn, user, f"alert_{action}")
        with tx(conn):
            a = alerts.get_alert(conn, aid)
            if a is None or not alerts.can_act(conn, user, a):
                access.audit(conn, user, f"alert_{action}", a and a["patient_id"], False)
                raise HTTPException(403, "Алерт назначен другому врачу")
            return alerts.transition(conn, a, action, user["id"])

    @api.get("/events/stream")
    async def events(token: str = ""):
        """SSE для врача: сначала все недоставленные алерты, затем новые события."""
        conn = connect(db_path)
        try:
            user = user_from_token(conn, token)
            if user["role"] != "doctor":
                raise HTTPException(403, "Поток событий доступен только врачу")
        finally:
            conn.close()
        q = broker.subscribe(user["id"])

        def pending() -> list[dict]:
            c = connect(db_path)
            try:
                return alerts.pending_for(c, user["id"])
            finally:
                c.close()

        async def gen():
            """Недоставленные алерты берутся из БД (другие процессы, перезапуск), новые события
            своего процесса приходят сразу через брокер. Повторно один алерт не отправляется."""
            sent: set[str] = set()
            last_ping = time.monotonic()
            try:
                yield "retry: 2000\n\n"
                while True:
                    for a in await asyncio.to_thread(pending):
                        if a["id"] not in sent:
                            sent.add(a["id"])
                            yield _sse("alert", a)
                    try:
                        ev = await asyncio.wait_for(q.get(), POLL_S)
                    except asyncio.TimeoutError:
                        if time.monotonic() - last_ping > 15:
                            last_ping = time.monotonic()
                            yield ": ping\n\n"
                        continue
                    if ev["type"] == "alert":
                        if ev["data"]["id"] in sent and ev["data"]["escalation_level"] == 0:
                            continue
                        sent.add(ev["data"]["id"])
                    yield _sse(ev["type"], ev["data"])
            finally:
                broker.unsubscribe(user["id"], q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @api.get("/patients/{pid}/messages")
    def get_messages(pid: str, user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        """Лента загружена получателем — сообщения считаются доставленными (не прочитанными)."""
        require_patient_access(conn, user, pid, "view_messages")
        if conn.execute("SELECT 1 FROM messages WHERE patient_id = ? AND delivered_at IS NULL AND sender_role != ?",
                        (pid, user["role"])).fetchone():
            with tx(conn):
                conn.execute("UPDATE messages SET delivered_at = ? WHERE patient_id = ? AND delivered_at IS NULL "
                             "AND sender_role != ?", (now(), pid, user["role"]))
        return [dict(r) for r in conn.execute("SELECT * FROM messages WHERE patient_id = ? ORDER BY id", (pid,))]

    @api.post("/patients/{pid}/messages")
    def send_message(pid: str, body: MessageIn, user: dict = Depends(current_user),
                     conn: sqlite3.Connection = Depends(get_conn)):
        require_patient_access(conn, user, pid, "send_message")
        require_consent(conn, user, pid, "send_message")
        if not body.text.strip():
            raise HTTPException(422, "Пустое сообщение")
        with tx(conn):
            cur = conn.execute("INSERT INTO messages (patient_id, sender_id, sender_role, text, created_at) "
                               "VALUES (?, ?, ?, ?, ?)", (pid, user["id"], user["role"], body.text.strip(), now()))
            msg = dict(conn.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone())
        if user["role"] == "patient":
            lead, _ = access.lead_doctor(conn, pid)
            if lead:
                broker.publish(lead, {"type": "message", "data": msg})
        return msg

    @api.post("/messages/{mid}/read")
    def read_message(mid: int, user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
        m = conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
        if m is None:
            raise HTTPException(403, "Нет доступа")
        require_patient_access(conn, user, m["patient_id"], "read_message")
        if m["sender_role"] == user["role"]:
            raise HTTPException(403, "Отметку «прочитано» ставит получатель")
        at = now()
        with tx(conn):
            conn.execute("UPDATE messages SET delivered_at = COALESCE(delivered_at, ?), read_at = COALESCE(read_at, ?) "
                         "WHERE id = ?", (at, at, mid))
        return dict(conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone())

    @api.post("/patients/{pid}/intake")
    def mark_intake(pid: str, body: Intake, user: dict = Depends(current_user),
                    conn: sqlite3.Connection = Depends(get_conn)):
        """Отметка о приёме за сегодня; повторная отметка за тот же день заменяет прежнюю."""
        if user["role"] != "patient":
            access.audit(conn, user, "intake", pid, False)
            raise HTTPException(403, "Отметку о приёме ставит пациент")
        require_patient_access(conn, user, pid, "intake")
        require_consent(conn, user, pid, "intake")
        with tx(conn):
            conn.execute("INSERT OR REPLACE INTO intake_marks (patient_id, date, status, reason) VALUES (?, ?, ?, ?)",
                         (pid, date.today().isoformat(), body.status, body.reason))
        return {"adherence": build_record(conn, pid)["adherence"]}

    @api.post("/patients/{pid}/referrals")
    def issue_referral(pid: str, body: ReferralIn, user: dict = Depends(current_user),
                       conn: sqlite3.Connection = Depends(get_conn)):
        """Направление к психиатру оформляет врач; система лишь подсказывает необходимость и срочность."""
        require_doctor(conn, user, "referral", pid)
        require_patient_access(conn, user, pid, "referral")
        if not body.reason.strip():
            raise HTTPException(422, "Укажите основание направления")
        at = now()
        with tx(conn):
            cur = conn.execute("INSERT INTO referrals (patient_id, doctor_id, necessity, urgency, reason, rule_id, "
                               "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (pid, user["id"], body.necessity, body.urgency, body.reason.strip(), body.rule_id, at, at))
            label = {"mandatory": "обязательно", "desirable": "желательно"}[body.necessity]
            urg = {"emergency": "экстренно", "urgent": "срочно", "planned": "планово"}[body.urgency]
            conn.execute("INSERT INTO decisions (patient_id, doctor_id, rule_id, rule_version, engine_version, action, "
                         "comment, evidence, at) VALUES (?, ?, ?, NULL, ?, 'confirm', ?, ?, ?)",
                         (pid, user["id"], body.rule_id or "REFERRAL", ENGINE_VERSION,
                          f"Направление к психиатру: {label}, {urg}. {body.reason.strip()}", dumps(body.model_dump()), at))
            if body.rule_id:
                alerts.close_for_decision(conn, pid, body.rule_id, user["id"], "направление")
            return dict(conn.execute("SELECT * FROM referrals WHERE id = ?", (cur.lastrowid,)).fetchone())

    @api.post("/referrals/{rid}/status")
    def referral_status(rid: int, body: ReferralStatus, user: dict = Depends(current_user),
                        conn: sqlite3.Connection = Depends(get_conn)):
        ref = conn.execute("SELECT * FROM referrals WHERE id = ?", (rid,)).fetchone()
        if ref is None:
            raise HTTPException(403, "Нет доступа")
        require_doctor(conn, user, "referral_status", ref["patient_id"])
        require_patient_access(conn, user, ref["patient_id"], "referral_status")
        with tx(conn):
            conn.execute("UPDATE referrals SET status = ?, note = COALESCE(?, note), updated_at = ? WHERE id = ?",
                         (body.status, body.note, now(), rid))
            return dict(conn.execute("SELECT * FROM referrals WHERE id = ?", (rid,)).fetchone())

    @api.post("/patients/{pid}/documents/extract")
    def extract_document(pid: str, body: DocumentIn, user: dict = Depends(current_user),
                         conn: sqlite3.Connection = Depends(get_conn)):
        """Извлечение из текста документа. Ничего не меняет в карточке: факты — «извлечено, не проверено»,
        в профиль попадает только то, что врач подтвердит (POST /safety-profile)."""
        require_doctor(conn, user, "extract_document", pid)
        require_patient_access(conn, user, pid, "extract_document")
        if not body.text.strip():
            raise HTTPException(422, "Пустой документ")
        result = extract(body.text)
        profile = build_record(conn, pid)["safety_profile"] or {}
        diff = []
        for key, fact in result["safety"].items():
            if fact["value"] is None:
                continue
            cur = profile.get(key)
            diff.append({"key": key, "current": cur, "extracted": fact["value"], "evidence": fact["evidence"],
                         "kind": "new" if cur is None else "same" if cur == fact["value"] else "conflict"})
        with tx(conn):
            cur = conn.execute("INSERT INTO documents (patient_id, uploaded_by, text, extraction, created_at) "
                               "VALUES (?, ?, ?, ?, ?)", (pid, user["id"], body.text, dumps(result), now()))
        return {"document_id": cur.lastrowid, "extraction": result, "diff": diff}

    @api.post("/patients/{pid}/safety-profile")
    def update_safety_profile(pid: str, body: SafetyFacts, user: dict = Depends(current_user),
                              conn: sqlite3.Connection = Depends(get_conn)):
        """Врач подтверждает факты профиля безопасности (из документа или со слов пациента).
        None — снова «неизвестно». Каждое изменение — запись в журнале решений."""
        require_doctor(conn, user, "safety_profile", pid)
        require_patient_access(conn, user, pid, "safety_profile")
        bad = set(body.facts) - _safety_keys()
        if not body.facts or bad:
            raise HTTPException(422, f"Неизвестные факты профиля: {sorted(bad)}" if bad else "Нет фактов")
        with tx(conn):
            profile = loads(conn.execute("SELECT safety_profile FROM patients WHERE id = ?", (pid,)).fetchone()[0]) or {}
            for k, v in body.facts.items():
                if v is None:
                    profile.pop(k, None)
                else:
                    profile[k] = v
            conn.execute("UPDATE patients SET safety_profile = ? WHERE id = ?", (dumps(profile), pid))
            src = f"документ №{body.document_id}" if body.source == "document" and body.document_id else (
                "документ" if body.source == "document" else "со слов пациента")
            comment = f"Профиль безопасности ({src}): " + ", ".join(
                f"{k} = {'да' if v else 'нет' if v is False else 'неизвестно'}" for k, v in body.facts.items())
            conn.execute("INSERT INTO decisions (patient_id, doctor_id, rule_id, rule_version, engine_version, action, "
                         "comment, evidence, at) VALUES (?, ?, 'SAFETY-PROFILE', NULL, ?, 'modify', ?, ?, ?)",
                         (pid, user["id"], ENGINE_VERSION, comment, dumps(body.facts), now()))
        return bundle(conn, pid, access.link_kind(conn, user, pid))

    @api.get("/analytics/aviandr")
    def analytics(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn),
                  scale: Literal["gad7", "phq9"] = "gad7", start_from: str | None = None, start_to: str | None = None,
                  age_min: int | None = None, age_max: int | None = None, sex: str | None = None,
                  indication: str | None = None, comorbidity: str | None = None, concomitant: str | None = None,
                  doctor_id: str | None = None):
        """Врач — свои курсы полностью; исследователь — все курсы обезличенно, ячейки n < 5 скрыты."""
        courses = build_courses(conn, "aviandr")
        if user["role"] == "doctor":
            courses, k, view, doctor_id = [c for c in courses if c["doctor_id"] == user["id"]], 1, "own", None
        elif user["role"] == "researcher":
            k, view = 5, "pseudonymized"
        else:
            access.audit(conn, user, "analytics", None, False)
            raise HTTPException(403, "Аналитика доступна врачу и исследователю")
        access.audit(conn, user, "analytics", None, True)
        filters = {"start_from": start_from, "start_to": start_to, "age_min": age_min, "age_max": age_max,
                   "sex": sex, "indication": indication, "comorbidity": comorbidity, "concomitant": concomitant,
                   "doctor_id": doctor_id}
        rep = aviandr_report(courses, filters, scale, k_min=k)
        return {**rep, "view": view, "synthetic": demo, "drug": load_card("aviandr")["trade_name"]}

    @api.post("/demo/reset")
    def demo_reset(user: dict = Depends(current_user)):
        if not demo:
            raise HTTPException(403, "Сброс доступен только в демо-режиме")
        conn = connect(db_path)
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            conn.execute("PRAGMA foreign_keys=OFF")
            with tx(conn):
                for t in tables:
                    conn.execute(f"DELETE FROM {t}")
            conn.execute("PRAGMA foreign_keys=ON")
            seed_demo(conn, courses=seed_courses)
        finally:
            conn.close()
        return {"ok": True}

    app.include_router(api)
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    app.state.db_path = db_path
    app.state.broker = broker
    return app


def app_from_env() -> FastAPI:
    """Фабрика для uvicorn с несколькими воркерами: настройки из переменных окружения."""
    import os
    return create_app(os.environ.get("KOMPAS_DB", "data/kompas.db"),
                      secret=os.environ.get("KOMPAS_SECRET", "dev-secret-change-me"),
                      escalate_after_s=float(os.environ.get("KOMPAS_ESCALATE_AFTER_S", "60")),
                      demo=os.environ.get("KOMPAS_DEMO", "1") == "1")
