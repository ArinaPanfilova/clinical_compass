"""Сервер: запись пациента и курсы терапии собираются из БД без потери смысла."""
from datetime import date, timedelta

import pytest

from kompas_core import evaluate_patient
from server.courses import build_courses
from server.db import connect, init_schema
from server.records import build_record
from server.seed import seed_demo
from synthetic.demo_patients import PATIENTS

TODAY = date.today()


def ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


COURSE = {
    "course_id": "AV-T1", "patient_key": "AVP-T1", "doctor_id": "doc-ivanova", "drug_id": "aviandr",
    "age": 40, "sex": "Ж", "indication": "F41.1", "comorbidities": ["cardiovascular"],
    "concomitant": ["antidepressant"], "start_date": ago(30), "end_date": None, "planned_weeks": 8,
    "stop_reason": None,
    "visits": [{"week": 0, "gad7": 16, "phq9": 9}, {"week": 2, "gad7": 12, "phq9": 8},
               {"week": 4, "gad7": None, "phq9": None}],
    "intake": {"taken": 20, "missed": 5, "unknown": 5},
    "adverse_events": [{"term": "сонливость", "severity": "mild", "serious": False, "week": 1}],
}

STOPPED = {**COURSE, "course_id": "AV-T2", "patient_key": "AVP-T2", "start_date": ago(70),
           "end_date": ago(42), "stop_reason": "adverse_event", "comorbidities": [], "concomitant": [],
           "visits": [{"week": 0, "gad7": 18, "phq9": 10}, {"week": 4, "gad7": 15, "phq9": 9}],
           "intake": {"taken": 25, "missed": 3, "unknown": 0},
           "adverse_events": [{"term": "головокружение", "severity": "severe", "serious": True, "week": 2}]}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    init_schema(c)
    seed_demo(c, courses=[COURSE, STOPPED])
    yield c
    c.close()


@pytest.mark.parametrize("p", PATIENTS, ids=lambda p: p["patient_id"])
def test_record_from_db_gives_same_evaluation(conn, p):
    src = evaluate_patient(p, drugs=["aviandr"])
    db = evaluate_patient(build_record(conn, p["patient_id"]), drugs=["aviandr"])
    assert db["triage_level"] == src["triage_level"]
    assert sorted(f["rule_id"] for f in db["findings"]) == sorted(f["rule_id"] for f in src["findings"])
    assert [d["status"] for d in db["drug_checks"]] == [d["status"] for d in src["drug_checks"]]


def test_unknown_safety_facts_stay_unknown(conn):
    sp = build_record(conn, "P-004")["safety_profile"]
    assert sp.get("epilepsy_or_organic_brain_lesion") is None
    assert sp["pregnancy"] is False


def test_record_has_contract_fields(conn):
    r = build_record(conn, "P-005")
    assert r["emergency_button"] is True
    assert r["therapy"]["current"][0]["mnn"] == "сертралин" and r["therapy"]["weeks_on_current"] == 6
    assert {a["scale"] for a in r["assessments"]} == {"phq9", "gad7"}
    phq = [a for a in r["assessments"] if a["scale"] == "phq9"]
    assert phq[-1]["answers"][8] == 3 and len(phq[-1]["answers"]) == 9
    assert r["diary"][0]["text"].startswith("Не вижу выхода")


def test_adherence_from_intake_marks(conn):
    a = build_record(conn, "P-006")["adherence"]
    assert a["confirmed"] > a["missed"] > 0
    assert a["confirmed"] + a["missed"] + a["unknown"] == 28


def test_missing_patient_raises(conn):
    with pytest.raises(KeyError):
        build_record(conn, "P-404")


def test_course_roundtrip(conn):
    x = next(c for c in build_courses(conn, "aviandr") if c["course_id"] == "AV-T1")
    assert x["visits"] == [{"week": 0, "gad7": 16, "phq9": 9}, {"week": 2, "gad7": 12, "phq9": 8}]
    assert x["intake"] == {"taken": 20, "missed": 5, "unknown": 5}
    assert x["adverse_events"] == [{"term": "сонливость", "severity": "mild", "serious": False, "week": 1}]
    assert x["comorbidities"] == ["cardiovascular"] and x["concomitant"] == ["antidepressant"]
    assert (x["stop_reason"], x["end_date"], x["doctor_id"]) == (None, None, "doc-ivanova")
    assert (x["age"], x["sex"], x["indication"], x["planned_weeks"]) == (40, "Ж", "F41.1", 8)


def test_stopped_course_roundtrip(conn):
    x = next(c for c in build_courses(conn, "aviandr") if c["course_id"] == "AV-T2")
    assert (x["stop_reason"], x["end_date"]) == ("adverse_event", ago(42))
    assert x["intake"] == {"taken": 25, "missed": 3, "unknown": 0}
    assert x["adverse_events"][0]["serious"] is True and x["adverse_events"][0]["week"] == 2


def test_scenario_patients_on_aviandr_are_courses(conn):
    keys = {c["patient_key"] for c in build_courses(conn, "aviandr")}
    assert {"P-006", "P-008"} <= keys and "P-005" not in keys


def test_active_cohort_course_appears_in_roster_finished_does_not(conn):
    links = dict(conn.execute("SELECT patient_id, active FROM care_links").fetchall())
    assert links["AVP-T1"] == 1 and links["AVP-T2"] == 0


def test_demo_users(conn):
    roles = dict(conn.execute("SELECT login, role FROM users").fetchall())
    assert roles["ivanova"] == roles["petrov"] == "doctor"
    assert roles["researcher"] == "researcher"
    assert roles["anna"] == "patient" and roles["maria"] == "patient"


def test_cohort_patients_have_readable_synthetic_names(conn):
    names = dict(conn.execute("SELECT id, name FROM patients WHERE id IN ('AVP-T1', 'AVP-T2')").fetchall())
    for name in names.values():
        assert not name.startswith("Пациент") and name.endswith("(синт.)")
        assert len(name.split()) == 3                                   # «Фамилия И. (синт.)»
    assert names["AVP-T1"].split()[0].endswith(("а", "я"))              # пол «Ж» → женская фамилия
