"""Сервер: направление к психиатру как действие врача; согласие пациента на обработку данных."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.db import connect

REF = {"necessity": "mandatory", "urgency": "urgent", "reason": "PHQ-9 п.9 = 2, нужна оценка психиатра",
       "rule_id": "SAFE-002"}


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


# ---------- Направление ----------

def test_doctor_issues_referral_patient_sees_it(client):
    r = client.post("/api/patients/P-005/referrals", json=REF, headers=auth(client, "ivanova"))
    assert r.status_code == 200, r.text
    ref = r.json()
    assert (ref["necessity"], ref["urgency"], ref["status"], ref["doctor_id"]) == ("mandatory", "urgent", "issued", "doc-ivanova")
    mine = client.get("/api/patients/P-005", headers=auth(client, "maria")).json()["referrals"]
    assert [(x["necessity"], x["urgency"]) for x in mine] == [("mandatory", "urgent")]


def test_referral_is_logged_as_doctor_decision(client):
    h = auth(client, "ivanova")
    client.post("/api/patients/P-005/referrals", json=REF, headers=h)
    d = client.get("/api/patients/P-005", headers=h).json()["decisions"][-1]
    assert d["finding_rule_id"] == "SAFE-002" and d["action"] == "confirm" and "Направление" in d["comment"]


def test_referral_status_flow(client):
    h = auth(client, "ivanova")
    ref = client.post("/api/patients/P-005/referrals", json=REF, headers=h).json()
    r = client.post(f"/api/referrals/{ref['id']}/status", json={"status": "scheduled", "note": "запись на 29.10"}, headers=h)
    assert r.json()["status"] == "scheduled" and r.json()["note"] == "запись на 29.10"
    assert client.post(f"/api/referrals/{ref['id']}/status", json={"status": "lost"}, headers=h).status_code == 422


@pytest.mark.parametrize("body", [{**REF, "necessity": "optional"}, {**REF, "urgency": "now"}, {**REF, "reason": " "}])
def test_referral_validation(client, body):
    assert client.post("/api/patients/P-005/referrals", json=body, headers=auth(client, "ivanova")).status_code == 422


@pytest.mark.parametrize("login", ["maria", "researcher", "petrov"])
def test_only_patients_doctor_issues_referral(client, login):
    assert client.post("/api/patients/P-005/referrals", json=REF, headers=auth(client, login)).status_code == 403


def test_status_change_only_by_doctor(client):
    ref = client.post("/api/patients/P-005/referrals", json=REF, headers=auth(client, "ivanova")).json()
    r = client.post(f"/api/referrals/{ref['id']}/status", json={"status": "completed"}, headers=auth(client, "maria"))
    assert r.status_code == 403


# ---------- Согласие ----------

def revoke(db_path, pid):
    connect(db_path).execute("DELETE FROM consents WHERE patient_id = ?", (pid,))


def test_demo_patients_have_consent(client):
    assert client.get("/api/me", headers=auth(client, "anna")).json()["consent_required"] is False


def test_without_consent_data_is_not_accepted_but_emergency_is(client, db_path):
    revoke(db_path, "P-001")
    h = auth(client, "anna")
    me = client.get("/api/me", headers=h).json()
    assert me["consent_required"] is True and me["consent"]["version"]
    report = {"questionnaires": [{"scale": "gad7", "answers": [1] * 7}]}
    assert client.post("/api/patients/P-001/self-report", json=report, headers=h).status_code == 403
    assert client.post("/api/patients/P-001/intake", json={"status": "taken"}, headers=h).status_code == 403
    assert client.post("/api/patients/P-001/messages", json={"text": "вопрос"}, headers=h).status_code == 403
    # Экстренное обращение принимается всегда: защита жизни и здоровья (152-ФЗ, ст. 10 ч. 2 п. 3)
    assert client.post("/api/patients/P-001/self-report", json={"emergency": True}, headers=h).status_code == 200


def test_accepting_consent_unlocks(client, db_path):
    revoke(db_path, "P-001")
    h = auth(client, "anna")
    version = client.get("/api/me", headers=h).json()["consent"]["version"]
    assert client.post("/api/consent", json={"version": version}, headers=h).status_code == 200
    assert client.get("/api/me", headers=h).json()["consent_required"] is False
    report = {"questionnaires": [{"scale": "gad7", "answers": [1] * 7}]}
    assert client.post("/api/patients/P-001/self-report", json=report, headers=h).status_code == 200


def test_consent_wrong_version_or_role(client, db_path):
    revoke(db_path, "P-001")
    assert client.post("/api/consent", json={"version": "old"}, headers=auth(client, "anna")).status_code == 422
    assert client.post("/api/consent", json={"version": "x"}, headers=auth(client, "ivanova")).status_code == 403


def test_doctor_has_no_consent_requirement(client):
    me = client.get("/api/me", headers=auth(client, "ivanova")).json()
    assert me["consent_required"] is False
