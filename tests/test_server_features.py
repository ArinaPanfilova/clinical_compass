"""Сервер: сообщения, отметки приёма, аналитика по ролям, демо-сброс, матрица доступа."""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.db import connect
from synthetic.aviandr_cohort import generate_courses

TODAY = date.today()
COHORT = generate_courses(40, seed=1, today=TODAY)
PETROV_COURSE = {
    "course_id": "AV-P1", "patient_key": "AVP-P1", "doctor_id": "doc-petrov", "drug_id": "aviandr",
    "age": 50, "sex": "М", "indication": "F41.1", "comorbidities": [], "concomitant": [],
    "start_date": (TODAY - timedelta(days=20)).isoformat(), "end_date": None, "planned_weeks": 8,
    "stop_reason": None, "visits": [{"week": 0, "gad7": 12, "phq9": 6}],
    "intake": {"taken": 10, "missed": 2, "unknown": 8}, "adverse_events": []}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "t.db"


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path, secret="s", seed_courses=COHORT + [PETROV_COURSE],
                               start_background=False)) as c:
        yield c


def auth(client, login):
    r = client.post("/api/auth/login", json={"login": login, "password": "demo"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- Сообщения ----------

def test_patient_message_delivered_and_read_by_doctor(client):
    pa, dr = auth(client, "anna"), auth(client, "ivanova")
    m = client.post("/api/patients/P-001/messages", json={"text": "Можно перенести визит?"}, headers=pa).json()
    assert m["sender_role"] == "patient" and m["delivered_at"] is None
    thread = client.get("/api/patients/P-001/messages", headers=dr).json()
    assert thread[-1]["text"] == "Можно перенести визит?" and thread[-1]["delivered_at"]
    assert client.post(f"/api/messages/{m['id']}/read", headers=dr).json()["read_at"]
    mine = client.get("/api/patients/P-001/messages", headers=pa).json()[-1]
    assert mine["delivered_at"] and mine["read_at"]


def test_doctor_reply_visible_to_patient(client):
    client.post("/api/patients/P-001/messages", json={"text": "Да, в четверг"}, headers=auth(client, "ivanova"))
    m = client.get("/api/patients/P-001/messages", headers=auth(client, "anna")).json()[-1]
    assert (m["text"], m["sender_role"]) == ("Да, в четверг", "doctor") and m["delivered_at"]


def test_only_recipient_marks_read(client):
    pa = auth(client, "anna")
    m = client.post("/api/patients/P-001/messages", json={"text": "вопрос"}, headers=pa).json()
    assert client.post(f"/api/messages/{m['id']}/read", headers=pa).status_code == 403


def test_empty_message_rejected(client):
    assert client.post("/api/patients/P-001/messages", json={"text": "  "}, headers=auth(client, "anna")).status_code == 422


# ---------- Приверженность ----------

def test_intake_mark_counts_today(client):
    h = auth(client, "alexey")
    before = client.get("/api/patients/P-008", headers=h).json()["record"]["adherence"]
    r = client.post("/api/patients/P-008/intake", json={"status": "missed", "reason": "забыл"}, headers=h)
    assert r.status_code == 200
    after = client.get("/api/patients/P-008", headers=h).json()["record"]["adherence"]
    assert after["missed"] == before["missed"] + 1 and after["unknown"] == before["unknown"]
    client.post("/api/patients/P-008/intake", json={"status": "taken"}, headers=h)   # исправил отметку за день
    fixed = client.get("/api/patients/P-008", headers=h).json()["record"]["adherence"]
    assert (fixed["missed"], fixed["confirmed"]) == (before["missed"], before["confirmed"] + 1)


# ---------- Аналитика ----------

def test_doctor_analytics_only_own_courses(client):
    r = client.get("/api/analytics/aviandr", headers=auth(client, "ivanova")).json()
    own = sum(c["doctor_id"] == "doc-ivanova" for c in COHORT) + 2      # + сценарии P-006, P-008
    assert r["n"] == own and r["k_min"] == 1 and r["synthetic"] is True


def test_researcher_sees_whole_cohort_with_k_anonymity(client):
    resp = client.get("/api/analytics/aviandr", headers=auth(client, "researcher"))
    r = resp.json()
    assert r["n"] == len(COHORT) + 3 and r["k_min"] == 5
    text = resp.text
    assert "P-00" not in text and "AVP-" not in text and "Анна" not in text


def test_analytics_filters_and_scale(client):
    h = auth(client, "researcher")
    men = client.get("/api/analytics/aviandr?sex=М&scale=phq9", headers=h).json()
    assert men["scale"] == "phq9"
    assert men["n"] is None or men["n"] < len(COHORT) + 3


def test_analytics_forbidden_for_patient(client):
    assert client.get("/api/analytics/aviandr", headers=auth(client, "anna")).status_code == 403


# ---------- Демо-сброс ----------

def test_demo_reset_restores_seed(client, db_path):
    h = auth(client, "anna")
    client.post("/api/patients/P-001/self-report", headers=h,
                json={"questionnaires": [{"scale": "phq9", "answers": [1] * 8 + [2]}]})
    assert client.post("/api/demo/reset", headers=h).status_code == 200
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE patient_id = 'P-001'").fetchone()[0] == 0
    assert client.get("/api/me", headers=auth(client, "anna")).status_code == 200


# ---------- Матрица доступа ----------

DECISION = {"finding_rule_id": "SAFE-002", "action": "confirm"}
MATRIX = [
    # (логин, метод, путь, тело, разрешено)
    ("anna", "GET", "/api/patients", None, False),
    ("anna", "GET", "/api/patients/P-001", None, True),
    ("anna", "GET", "/api/patients/P-002", None, False),
    ("anna", "POST", "/api/patients/P-001/self-report", {}, True),
    ("anna", "POST", "/api/patients/P-002/self-report", {}, False),
    ("anna", "POST", "/api/patients/P-001/decisions", DECISION, False),
    ("anna", "GET", "/api/patients/P-001/decisions", None, False),
    ("anna", "GET", "/api/alerts", None, False),
    ("anna", "GET", "/api/analytics/aviandr", None, False),
    ("anna", "GET", "/api/patients/P-001/messages", None, True),
    ("anna", "GET", "/api/patients/P-002/messages", None, False),
    ("anna", "POST", "/api/patients/P-002/messages", {"text": "x"}, False),
    ("anna", "POST", "/api/patients/P-001/intake", {"status": "taken"}, True),
    ("anna", "POST", "/api/patients/P-002/intake", {"status": "taken"}, False),
    ("ivanova", "GET", "/api/patients", None, True),
    ("ivanova", "GET", "/api/patients/P-001", None, True),
    ("ivanova", "GET", "/api/patients/AVP-P1", None, False),
    ("ivanova", "POST", "/api/patients/P-001/self-report", {}, False),
    ("ivanova", "POST", "/api/patients/P-001/intake", {"status": "taken"}, False),
    ("ivanova", "POST", "/api/patients/P-001/decisions", DECISION, True),
    ("ivanova", "POST", "/api/patients/AVP-P1/decisions", DECISION, False),
    ("ivanova", "GET", "/api/patients/AVP-P1/messages", None, False),
    ("ivanova", "GET", "/api/analytics/aviandr", None, True),
    ("petrov", "GET", "/api/patients/P-001", None, False),
    ("petrov", "POST", "/api/patients/P-001/decisions", DECISION, False),
    ("petrov", "GET", "/api/patients/P-001/messages", None, False),
    ("researcher", "GET", "/api/patients", None, False),
    ("researcher", "GET", "/api/patients/P-001", None, False),
    ("researcher", "GET", "/api/alerts", None, False),
    ("researcher", "GET", "/api/patients/P-001/messages", None, False),
    ("researcher", "POST", "/api/patients/P-001/decisions", DECISION, False),
    ("researcher", "GET", "/api/analytics/aviandr", None, True),
]


@pytest.mark.parametrize("login,method,path,body,allowed", MATRIX,
                         ids=[f"{m[0]}-{m[1]}-{m[2]}" for m in MATRIX])
def test_access_matrix(client, login, method, path, body, allowed):
    r = client.request(method, path, headers=auth(client, login), json=body)
    if allowed:
        assert r.status_code not in (401, 403), r.text
    else:
        assert r.status_code == 403, r.text


@pytest.mark.parametrize("method,path", sorted({(m[1], m[2]) for m in MATRIX}))
def test_every_endpoint_requires_login(client, method, path):
    assert client.request(method, path, json={}).status_code == 401
