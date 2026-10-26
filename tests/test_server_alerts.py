"""Сервер: самоотчёт → данные и алерт в одной транзакции → доставка, принятие, эскалация."""
import asyncio
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from server import alerts
from server.app import create_app
from server.db import connect, tx


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "t.db"


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path, secret="s", seed_courses=[], start_background=False)) as c:
        yield c


def auth(client, login):
    r = client.post("/api/auth/login", json={"login": login, "password": "demo"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def report(item9=2, **extra):
    body = {"questionnaires": [{"scale": "phq9", "answers": [1] * 8 + [item9]},
                               {"scale": "gad7", "answers": [1] * 7}]}
    body.update(extra)
    return body


def open_alerts(client, pid, rule):
    return [a for a in client.get("/api/alerts", headers=auth(client, "ivanova")).json()
            if a["patient_id"] == pid and a["rule_id"] == rule and a["status"] != "closed"]


def count(db_path, sql, *args):
    return connect(db_path).execute(sql, args).fetchone()[0]


def test_item9_creates_urgent_alert_for_lead_doctor(client):
    r = client.post("/api/patients/P-001/self-report", json=report(2), headers=auth(client, "anna"))
    assert r.status_code == 200, r.text
    assert r.json()["patient_messages"]
    [a] = open_alerts(client, "P-001", "SAFE-002")
    assert (a["priority"], a["status"], a["assigned_to"]) == ("urgent", "created", "doc-ivanova")
    assert a["saved_at"] <= a["created_at"]
    assert a["patient_name"].startswith("Анна")


def test_emergency_button_creates_emergency_alert(client):
    client.post("/api/patients/P-001/self-report", json={"emergency": True}, headers=auth(client, "anna"))
    [a] = open_alerts(client, "P-001", "SAFE-001")
    assert a["priority"] == "emergency"


def test_retry_with_same_key_changes_nothing(client, db_path):
    h = {**auth(client, "anna"), "Idempotency-Key": "k-1"}
    before = count(db_path, "SELECT COUNT(*) FROM assessments WHERE patient_id = 'P-001'")
    first = client.post("/api/patients/P-001/self-report", json=report(2, diary_text="тест"), headers=h).json()
    second = client.post("/api/patients/P-001/self-report", json=report(2, diary_text="тест"), headers=h).json()
    assert first == second
    assert count(db_path, "SELECT COUNT(*) FROM assessments WHERE patient_id = 'P-001'") == before + 2
    assert count(db_path, "SELECT COUNT(*) FROM diary WHERE patient_id = 'P-001' AND text = 'тест'") == 1
    assert len(open_alerts(client, "P-001", "SAFE-002")) == 1


def test_open_alert_is_not_duplicated_by_new_report(client):
    h = auth(client, "anna")
    client.post("/api/patients/P-001/self-report", json=report(2), headers={**h, "Idempotency-Key": "a"})
    client.post("/api/patients/P-001/self-report", json=report(3), headers={**h, "Idempotency-Key": "b"})
    assert len(open_alerts(client, "P-001", "SAFE-002")) == 1


def confirm(client, rule):
    r = client.post("/api/patients/P-001/decisions", headers=auth(client, "ivanova"),
                    json={"finding_rule_id": rule, "action": "confirm"})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("unrelated", [{"emergency": True}, {"medication_taken": "taken"},
                                       {"diary_text": "сегодня спокойнее"}])
def test_decided_alert_is_not_raised_again_by_unrelated_report(client, unrelated):
    # Врач уже решил по п.9; отметка о приёме или экстренная кнопка не дают нового повода по тем же ответам
    h = auth(client, "anna")
    client.post("/api/patients/P-001/self-report", json=report(2), headers=h)
    confirm(client, "SAFE-002")
    client.post("/api/patients/P-001/self-report", json=unrelated, headers=h)
    assert open_alerts(client, "P-001", "SAFE-002") == []


def test_decided_alert_is_raised_again_by_new_questionnaire_with_same_answer(client):
    h = auth(client, "anna")
    client.post("/api/patients/P-001/self-report", json=report(2), headers=h)
    confirm(client, "SAFE-002")
    client.post("/api/patients/P-001/self-report", json=report(2), headers=h)
    assert len(open_alerts(client, "P-001", "SAFE-002")) == 1


def test_decided_emergency_is_raised_again_only_by_new_press(client):
    h = auth(client, "anna")
    client.post("/api/patients/P-001/self-report", json={"emergency": True}, headers=h)
    confirm(client, "SAFE-001")
    client.post("/api/patients/P-001/self-report", json={"medication_taken": "taken"}, headers=h)
    assert open_alerts(client, "P-001", "SAFE-001") == []
    client.post("/api/patients/P-001/self-report", json={"emergency": True}, headers=h)
    assert len(open_alerts(client, "P-001", "SAFE-001")) == 1


def test_invalid_questionnaire_rejected_and_nothing_saved(client, db_path):
    before = count(db_path, "SELECT COUNT(*) FROM assessments")
    bad = {"questionnaires": [{"scale": "phq9", "answers": [5] * 9}], "diary_text": "не должно сохраниться"}
    assert client.post("/api/patients/P-001/self-report", json=bad, headers=auth(client, "anna")).status_code == 422
    assert count(db_path, "SELECT COUNT(*) FROM assessments") == before
    assert count(db_path, "SELECT COUNT(*) FROM diary WHERE text = 'не должно сохраниться'") == 0


def test_only_the_patient_can_self_report(client):
    assert client.post("/api/patients/P-001/self-report", json=report(0), headers=auth(client, "ivanova")).status_code == 403
    assert client.post("/api/patients/P-002/self-report", json=report(0), headers=auth(client, "anna")).status_code == 403


def test_lifecycle_ack_accept_then_decision_closes(client):
    client.post("/api/patients/P-001/self-report", json=report(2), headers=auth(client, "anna"))
    h = auth(client, "ivanova")
    [a] = open_alerts(client, "P-001", "SAFE-002")
    assert client.post(f"/api/alerts/{a['id']}/ack", headers=h).json()["status"] == "delivered"
    acc = client.post(f"/api/alerts/{a['id']}/accept", headers=h).json()
    assert acc["status"] == "accepted" and acc["accepted_by"] == "doc-ivanova" and acc["delivered_at"]
    d = client.post("/api/patients/P-001/decisions", headers=h,
                    json={"finding_rule_id": "SAFE-002", "action": "confirm"})
    assert d.status_code == 200 and d.json()["rule_version"]
    closed = next(x for x in client.get("/api/alerts", headers=h).json() if x["id"] == a["id"])
    assert closed["status"] == "closed"
    assert [e["status"] for e in closed["history"]] == ["created", "delivered", "accepted", "closed"]


def test_unrelated_doctor_cannot_touch_alert(client):
    client.post("/api/patients/P-001/self-report", json=report(2), headers=auth(client, "anna"))
    [a] = open_alerts(client, "P-001", "SAFE-002")
    assert client.post(f"/api/alerts/{a['id']}/accept", headers=auth(client, "petrov")).status_code == 403


def test_reject_requires_reason(client):
    r = client.post("/api/patients/P-001/decisions", headers=auth(client, "ivanova"),
                    json={"finding_rule_id": "SAFE-002", "action": "reject"})
    assert r.status_code == 422


def test_patient_cannot_make_clinical_decisions(client):
    r = client.post("/api/patients/P-001/decisions", headers=auth(client, "anna"),
                    json={"finding_rule_id": "SAFE-002", "action": "confirm"})
    assert r.status_code == 403


def test_escalation_to_deputy_after_timeout(client, db_path):
    client.post("/api/patients/P-001/self-report", json=report(2), headers=auth(client, "anna"))
    conn = connect(db_path)
    soon = datetime.now(timezone.utc) + timedelta(seconds=10)
    with tx(conn):
        assert alerts.escalate_due(conn, soon, after_s=60) == []
    later = datetime.now(timezone.utc) + timedelta(seconds=61)
    with tx(conn):
        [e] = alerts.escalate_due(conn, later, after_s=60)
    assert (e["assigned_to"], e["escalation_level"], e["status"]) == ("doc-petrov", 1, "created")
    assert e["history"][-1]["status"] == "escalated"
    with tx(conn):
        assert alerts.escalate_due(conn, later + timedelta(hours=1), after_s=60) == []   # один уровень
    assert client.get("/api/patients/P-001", headers=auth(client, "petrov")).status_code == 200


def test_accepted_alert_is_not_escalated(client, db_path):
    client.post("/api/patients/P-001/self-report", json=report(2), headers=auth(client, "anna"))
    [a] = open_alerts(client, "P-001", "SAFE-002")
    client.post(f"/api/alerts/{a['id']}/accept", headers=auth(client, "ivanova"))
    conn = connect(db_path)
    with tx(conn):
        assert alerts.escalate_due(conn, datetime.now(timezone.utc) + timedelta(hours=1), after_s=60) == []


def test_pending_until_delivered(client, db_path):
    client.post("/api/patients/P-001/self-report", json=report(2), headers=auth(client, "anna"))
    [a] = open_alerts(client, "P-001", "SAFE-002")
    assert a["id"] in {x["id"] for x in alerts.pending_for(connect(db_path), "doc-ivanova")}
    client.post(f"/api/alerts/{a['id']}/ack", headers=auth(client, "ivanova"))
    assert a["id"] not in {x["id"] for x in alerts.pending_for(connect(db_path), "doc-ivanova")}


def test_seeded_scenario_alerts_are_accepted_not_escalating(db_path, client):
    """Демо-алерты сценариев уже приняты лечащим врачом — фоновая эскалация их не трогает."""
    conn = connect(db_path)
    rows = conn.execute("SELECT status, assigned_to FROM alerts WHERE patient_id = 'P-005'").fetchall()
    assert rows and all(tuple(r) == ("accepted", "doc-ivanova") for r in rows)


def test_broker_delivers_across_threads():
    async def run():
        b = alerts.Broker()
        b.bind(asyncio.get_running_loop())
        q = b.subscribe("doc-1")
        threading.Thread(target=b.publish, args=("doc-1", {"type": "alert", "data": {"id": "x"}})).start()
        ev = await asyncio.wait_for(q.get(), 1)
        b.unsubscribe("doc-1", q)
        b.publish("doc-1", {"type": "alert", "data": {"id": "y"}})   # отписанным не доставляется
        return ev, q.qsize()
    ev, left = asyncio.run(run())
    assert ev["data"]["id"] == "x" and left == 0


def test_stream_requires_doctor_token(client):
    assert client.get("/api/events/stream?token=bad").status_code == 401
    token = auth(client, "anna")["Authorization"][7:]
    assert client.get(f"/api/events/stream?token={token}").status_code == 403
