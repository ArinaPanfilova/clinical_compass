"""Сервер: врач загружает текст документа → извлечённые факты с цитатами → врач подтверждает → профиль."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.db import connect

DOC = ("Выписка. Дата: 20.10.2026. Ds: F41.1 Генерализованное тревожное расстройство. Сопут.: ГБ II ст. "
       "Эпилепсию отрицает. Беременность исключена, не кормит грудью. СКФ 85 мл/мин. Печёночной "
       "недостаточности нет. Аллергию отрицает. Ингибиторы МАО не принимал. Терапия: сертралин 50 мг утром.")
ALL_FALSE = {k: False for k in (
    "hypersensitivity_aviandr", "epilepsy_or_organic_brain_lesion", "maoi_within_2_weeks", "renal_gfr_below_60",
    "hepatic_insufficiency", "pregnancy", "breastfeeding", "cardiovascular_disease", "endocrine_disorder",
    "substance_dependence", "lactose_intolerance", "drives_vehicles")}


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


def test_extract_returns_facts_with_quotes_and_diff(client):
    r = client.post("/api/patients/P-004/documents/extract", json={"text": DOC}, headers=auth(client, "ivanova"))
    assert r.status_code == 200, r.text
    body = r.json()
    ep = body["extraction"]["safety"]["epilepsy_or_organic_brain_lesion"]
    assert ep["value"] is False and DOC[ep["evidence"]["start"]:ep["evidence"]["end"]] == ep["evidence"]["quote"]
    diff = {d["key"]: d for d in body["diff"]}
    assert diff["epilepsy_or_organic_brain_lesion"]["kind"] == "new"          # было неизвестно
    assert diff["pregnancy"]["kind"] == "same"                                # уже было «нет»
    assert body["document_id"] and body["extraction"]["status"] == "extracted_unverified"


def test_extract_flags_conflict_with_profile(client):
    doc = "Эпилепсия с 2015 года, принимает вальпроевую кислоту."
    r = client.post("/api/patients/P-002/documents/extract", json={"text": doc}, headers=auth(client, "ivanova"))
    diff = {d["key"]: d for d in r.json()["diff"]}
    assert diff["epilepsy_or_organic_brain_lesion"]["kind"] == "same"         # у Сергея М. эпилепсия уже есть
    r = client.post("/api/patients/P-001/documents/extract", json={"text": doc}, headers=auth(client, "ivanova"))
    diff = {d["key"]: d for d in r.json()["diff"]}
    assert diff["epilepsy_or_organic_brain_lesion"]["kind"] == "conflict"     # у Анны было «нет»


@pytest.mark.parametrize("login,pid", [("anna", "P-001"), ("researcher", "P-001"), ("petrov", "P-001")])
def test_extract_only_for_patients_doctor(client, login, pid):
    r = client.post(f"/api/patients/{pid}/documents/extract", json={"text": DOC}, headers=auth(client, login))
    assert r.status_code == 403


@pytest.mark.parametrize("text", ["   ", "x" * 60_001])
def test_extract_rejects_empty_or_huge(client, text):
    r = client.post("/api/patients/P-004/documents/extract", json={"text": text}, headers=auth(client, "ivanova"))
    assert r.status_code == 422


def test_document_is_stored_for_audit(client, db_path):
    client.post("/api/patients/P-004/documents/extract", json={"text": DOC}, headers=auth(client, "ivanova"))
    row = connect(db_path).execute("SELECT patient_id, uploaded_by, text FROM documents").fetchone()
    assert tuple(row) == ("P-004", "doc-ivanova", DOC)


def test_confirmed_facts_change_drug_check(client):
    h = auth(client, "ivanova")
    before = client.get("/api/patients/P-004", headers=h).json()["evaluation"]["drug_checks"][0]["status"]
    assert before == "insufficient_data"
    r = client.post("/api/patients/P-004/safety-profile", headers=h,
                    json={"facts": ALL_FALSE, "source": "document", "document_id": None})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["record"]["safety_profile"]["epilepsy_or_organic_brain_lesion"] is False
    assert b["evaluation"]["drug_checks"][0]["status"] == "can_be_considered"
    assert b["decisions"][-1]["finding_rule_id"] == "SAFETY-PROFILE"


def test_profile_value_can_be_reset_to_unknown(client):
    h = auth(client, "ivanova")
    r = client.post("/api/patients/P-001/safety-profile", headers=h, json={"facts": {"pregnancy": None}, "source": "manual"})
    assert r.json()["record"]["safety_profile"].get("pregnancy") is None


@pytest.mark.parametrize("facts", [{"unknown_key": True}, {"pregnancy": "да"}, {}])
def test_profile_rejects_bad_facts(client, facts):
    r = client.post("/api/patients/P-001/safety-profile", headers=auth(client, "ivanova"),
                    json={"facts": facts, "source": "manual"})
    assert r.status_code == 422


@pytest.mark.parametrize("login", ["anna", "researcher", "petrov"])
def test_profile_only_by_patients_doctor(client, login):
    r = client.post("/api/patients/P-001/safety-profile", headers=auth(client, login),
                    json={"facts": {"pregnancy": False}, "source": "manual"})
    assert r.status_code == 403
