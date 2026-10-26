"""Алерты: создание в транзакции с данными, жизненный цикл, эскалация, доставка подписчикам.

Жизненный цикл: created → delivered (клиент врача подтвердил получение) → accepted (врач принял
в работу) → closed (врач принял решение по находке). Эскалация: срочный или экстренный алерт,
не принятый за заданное время, переназначается заместителю — заранее указанному в связи
«врач–пациент», а не любому сотруднику. Алерт — ситуация, требующая действия по протоколу,
а не прогноз суицида (NICE NG225).
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from . import access
from .db import now

ESCALATING = ("emergency", "urgent")
TRANSITIONS = {"ack": ("created", "delivered"), "accept": ("created", "delivered", "accepted"),
               "close": ("created", "delivered", "accepted", "closed")}


def _event(conn, aid: str, status: str, user_id: str | None = None, note: str | None = None, at: str | None = None):
    conn.execute("INSERT INTO alert_events (alert_id, status, at, user_id, note) VALUES (?, ?, ?, ?, ?)",
                 (aid, status, at or now(), user_id, note))


def get_alert(conn: sqlite3.Connection, aid: str) -> dict | None:
    r = conn.execute("SELECT a.*, p.name AS patient_name FROM alerts a JOIN patients p ON p.id = a.patient_id "
                     "WHERE a.id = ?", (aid,)).fetchone()
    if r is None:
        return None
    a = dict(r)
    a["patient_name"] = a["patient_name"].replace(" (синт.)", "")
    a["history"] = [dict(e) for e in conn.execute("SELECT status, at, user_id, note FROM alert_events "
                                                  "WHERE alert_id = ? ORDER BY id", (aid,))]
    return a


def create_alerts(conn: sqlite3.Connection, pid: str, evaluation: dict, saved_at: str,
                  created_at: str | None = None, new_facts: tuple[str, ...] | None = None) -> list[dict]:
    """Алерты по находкам kind='alert'. Открытый алерт по тому же правилу не дублируется.

    new_facts — префиксы фактов, которые принёс этот самоотчёт. Если по правилу уже был закрытый
    решением врача алерт, новый создаётся только когда правило опирается на свежие данные:
    иначе отметка о приёме подняла бы тот же сигнал по тем же старым ответам.
    """
    lead, _ = access.lead_doctor(conn, pid)
    if lead is None:
        return []
    out = []
    for f in evaluation["findings"]:
        if f["kind"] != "alert":
            continue
        statuses = {r[0] for r in conn.execute("SELECT status FROM alerts WHERE patient_id = ? AND rule_id = ?",
                                               (pid, f["rule_id"]))}
        if statuses - {"closed"}:
            continue
        if statuses and new_facts is not None and not any(k.startswith(new_facts) for k in f["evidence"]):
            continue
        aid, at = uuid.uuid4().hex, created_at or now()
        conn.execute("INSERT INTO alerts (id, patient_id, rule_id, priority, title, assigned_to, saved_at, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (aid, pid, f["rule_id"], f["priority"], f["title"], lead,
                                                         saved_at, at))
        _event(conn, aid, "created", at=at)
        out.append(get_alert(conn, aid))
    return out


def alerts_for(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    """Алерты, назначенные врачу, и алерты его пациентов (в т.ч. эскалированные заместителю)."""
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM alerts WHERE assigned_to = ? OR patient_id IN "
        "(SELECT patient_id FROM care_links WHERE doctor_id = ? AND active = 1) ORDER BY created_at DESC",
        (user_id, user_id))]
    return [get_alert(conn, i) for i in ids]


def pending_for(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    ids = [r[0] for r in conn.execute("SELECT id FROM alerts WHERE assigned_to = ? AND status = 'created' "
                                      "ORDER BY created_at", (user_id,))]
    return [get_alert(conn, i) for i in ids]


def can_act(conn: sqlite3.Connection, user: dict, alert: dict) -> bool:
    return user["role"] == "doctor" and (alert["assigned_to"] == user["id"]
                                         or access.link_kind(conn, user, alert["patient_id"]) == "lead")


def transition(conn: sqlite3.Connection, alert: dict, action: str, user_id: str, note: str | None = None) -> dict:
    """ack | accept | close. Повторное действие не меняет уже пройденные метки времени."""
    if alert["status"] not in TRANSITIONS[action]:
        return alert
    at = now()
    if action == "ack":
        conn.execute("UPDATE alerts SET status = 'delivered', delivered_at = COALESCE(delivered_at, ?) WHERE id = ?",
                     (at, alert["id"]))
        _event(conn, alert["id"], "delivered", user_id, note, at)
    elif action == "accept" and alert["status"] != "accepted":
        conn.execute("UPDATE alerts SET status = 'accepted', delivered_at = COALESCE(delivered_at, ?), "
                     "accepted_at = ?, accepted_by = ? WHERE id = ?", (at, at, user_id, alert["id"]))
        _event(conn, alert["id"], "accepted", user_id, note, at)
    elif action == "close" and alert["status"] != "closed":
        conn.execute("UPDATE alerts SET status = 'closed', closed_at = ? WHERE id = ?", (at, alert["id"]))
        _event(conn, alert["id"], "closed", user_id, note, at)
    return get_alert(conn, alert["id"])


def close_for_decision(conn: sqlite3.Connection, pid: str, rule_id: str, user_id: str, action: str) -> None:
    for (aid,) in conn.execute("SELECT id FROM alerts WHERE patient_id = ? AND rule_id = ? AND status != 'closed'",
                               (pid, rule_id)).fetchall():
        transition(conn, get_alert(conn, aid), "close", user_id, f"решение врача: {action}")


def has_escalation_candidates(conn: sqlite3.Connection) -> bool:
    return conn.execute(f"SELECT 1 FROM alerts WHERE status IN ('created', 'delivered') AND escalation_level = 0 "
                        f"AND priority IN {ESCALATING} LIMIT 1").fetchone() is not None


def escalate_due(conn: sqlite3.Connection, at: datetime, after_s: float) -> list[dict]:
    """Непринятые срочные и экстренные алерты старше after_s → заместителю (один уровень)."""
    rows = conn.execute(
        "SELECT a.id, a.created_at, cl.deputy_id FROM alerts a JOIN care_links cl "
        "ON cl.patient_id = a.patient_id AND cl.doctor_id = a.assigned_to AND cl.active = 1 "
        f"WHERE a.status IN ('created', 'delivered') AND a.priority IN {ESCALATING} "
        "AND a.escalation_level = 0 AND cl.deputy_id IS NOT NULL").fetchall()
    out = []
    for r in rows:
        if datetime.fromisoformat(r["created_at"]) + timedelta(seconds=after_s) > at:
            continue
        conn.execute("UPDATE alerts SET assigned_to = ?, escalation_level = 1, status = 'created' WHERE id = ?",
                     (r["deputy_id"], r["id"]))
        _event(conn, r["id"], "escalated", r["deputy_id"], f"не принят за {int(after_s)} с — передан заместителю")
        out.append(get_alert(conn, r["id"]))
    return out


class Broker:
    """Доставка событий подключённым врачам (SSE). publish безопасен из любых потоков."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self.lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self.lock:
            self.subs[user_id].add(q)
        return q

    def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        with self.lock:
            self.subs[user_id].discard(q)

    def publish(self, user_id: str, event: dict) -> None:
        if self.loop is None:
            return
        with self.lock:
            queues = list(self.subs.get(user_id, ()))
        for q in queues:
            self.loop.call_soon_threadsafe(q.put_nowait, event)
