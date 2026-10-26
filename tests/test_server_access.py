"""Сервер: вход, раздельные права ролей, замещение только через эскалацию, аудит отказов."""
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.auth import make_token
from server.db import connect

TODAY = date.today()
SECRET = "test-secret"


def course(cid: str, doctor: str, active: bool = True) -> dict:
    start = (TODAY - timedelta(days=20)).isoformat()
    return {"course_id": cid, "patient_key": f"P{cid}", "doctor_id": doctor, "drug_id": "aviandr",
            "age": 50, "sex": "М", "indication": "F41.1", "comorbidities": [], "concomitant": [],
            "start_date": start, "end_date": None if active else (TODAY - timedelta(days=2)).isoformat(),
            "planned_weeks": 8, "stop_reason": None if active else "completed",
            "visits": [{"week": 0, "gad7": 12, "phq9": 6}], "intake": {"taken": 10, "missed": 2, "unknown": 8},
            "adverse_events": []}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "t.db"


@pytest.fixture
def client(db_path):
    app = create_app(db_path, secret=SECRET, seed_courses=[course("I1", "doc-ivanova"), course("P1", "doc-petrov")],
                     start_background=False)
    with TestClient(app) as c:
        yield c


def auth(client, login, password="demo"):
    r = client.post("/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_login_returns_role(client):
    r = client.post("/api/auth/login", json={"login": "anna", "password": "demo"})
    assert r.status_code == 200
    assert r.json()["user"] == {"id": "pat-P-001", "role": "patient", "display_name": "Анна К.", "patient_id": "P-001"}


@pytest.mark.parametrize("login,password", [("anna", "wrong"), ("nobody", "demo")])
def test_bad_credentials_401(client, login, password):
    assert client.post("/api/auth/login", json={"login": login, "password": password}).status_code == 401


def test_token_required_and_checked(client):
    assert client.get("/api/me").status_code == 401
    good = make_token("doc-ivanova", SECRET)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {good}"}).json()["role"] == "doctor"
    forged = make_token("doc-ivanova", "other-secret")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = make_token("doc-ivanova", SECRET, ttl_s=10, now=time.time() - 100)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_doctor_sees_only_own_active_patients(client):
    ids = {b["record"]["patient_id"] for b in client.get("/api/patients", headers=auth(client, "ivanova")).json()}
    assert {f"P-00{i}" for i in range(1, 9)} | {"PI1"} == ids


def test_patient_sees_only_own_card(client):
    h = auth(client, "anna")
    assert client.get("/api/patients/P-001", headers=h).status_code == 200
    assert client.get("/api/patients/P-002", headers=h).status_code == 403
    assert client.get("/api/patients", headers=h).status_code == 403


def test_researcher_never_opens_cards(client):
    h = auth(client, "researcher")
    assert client.get("/api/patients", headers=h).status_code == 403
    assert client.get("/api/patients/P-001", headers=h).status_code == 403


def test_other_doctor_has_no_access_without_escalation(client):
    h = auth(client, "petrov")
    assert client.get("/api/patients/P-001", headers=h).status_code == 403
    assert {b["record"]["patient_id"] for b in client.get("/api/patients", headers=h).json()} == {"PP1"}


def test_deputy_gets_access_only_to_patient_with_escalated_alert(client, db_path):
    c = connect(db_path)
    c.execute("INSERT INTO alerts (id, patient_id, rule_id, priority, title, status, assigned_to, escalation_level, "
              "saved_at, created_at) VALUES ('a1', 'P-001', 'SAFE-002', 'urgent', 't', 'created', 'doc-petrov', 1, 'x', 'x')")
    c.close()
    h = auth(client, "petrov")
    assert client.get("/api/patients/P-001", headers=h).status_code == 200
    assert client.get("/api/patients/P-002", headers=h).status_code == 403
    listed = {b["record"]["patient_id"]: b["link"] for b in client.get("/api/patients", headers=h).json()}
    assert listed == {"PP1": "lead", "P-001": "deputy"}


def test_unknown_patient_is_403_not_404(client):
    """Чужой и несуществующий ID неразличимы — перебором нельзя узнать, кто есть в базе."""
    assert client.get("/api/patients/P-404", headers=auth(client, "ivanova")).status_code == 403


def test_card_access_and_denials_are_audited(client, db_path):
    h = auth(client, "anna")
    client.get("/api/patients/P-001", headers=h)
    client.get("/api/patients/P-002", headers=h)
    rows = connect(db_path).execute("SELECT user_id, patient_id, allowed FROM audit_log "
                                    "WHERE action = 'view_patient' ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("pat-P-001", "P-001", 1), ("pat-P-001", "P-002", 0)]


def test_bundle_contains_evaluation(client):
    h = auth(client, "ivanova")
    client.post("/api/patients/P-005/decisions", headers=h, json={"finding_rule_id": "SAFE-002", "action": "confirm"})
    b = client.get("/api/patients/P-005", headers=h).json()
    assert b["evaluation"]["triage_level"] == "emergency"
    assert b["record"]["name"].startswith("Мария")
    assert b["link"] == "lead"
    assert {a["rule_id"] for a in b["alerts"]} >= {"SAFE-001", "SAFE-002"}
    assert [(d["finding_rule_id"], d["action"]) for d in b["decisions"]] == [("SAFE-002", "confirm")]
    assert b["therapy_options"][0]["guideline"]["id"] == "301_3"            # F32.1 → КР депрессии


def test_patient_bundle_hides_doctor_workflow(client):
    """Пациенту не нужны служебные алерты и журнал решений врача."""
    b = client.get("/api/patients/P-005", headers=auth(client, "maria")).json()
    assert b["alerts"] == [] and b["decisions"] == [] and b["therapy_options"] == []
