"""Синтетическая когорта курсов Авиандра: соответствие инструкции и пригодность для аналитики."""
from datetime import date, timedelta

import pytest

from kompas_core.analytics import aviandr_report, outcome_group
from synthetic.aviandr_cohort import AE_TERMS, DEMO_DOCTOR, generate_courses

TODAY = date(2026, 10, 26)


@pytest.fixture(scope="module")
def cohort():
    return generate_courses(300, seed=7, today=TODAY)


def test_size_and_determinism(cohort):
    assert len(cohort) == 300
    assert generate_courses(300, seed=7, today=TODAY) == cohort
    assert generate_courses(300, seed=8, today=TODAY) != cohort


def test_registered_conditions(cohort):
    """Взрослые; F43.2 — курс 4–6 недель по инструкции; F41.1 — 8–12 недель (допущение генератора)."""
    assert all(c["age"] >= 18 for c in cohort)
    assert {c["indication"] for c in cohort} == {"F41.1", "F43.2"}
    assert all(c["planned_weeks"] <= 6 for c in cohort if c["indication"] == "F43.2")
    assert all(8 <= c["planned_weeks"] <= 12 for c in cohort if c["indication"] == "F41.1")


def test_adverse_event_terms_from_instruction(cohort):
    aes = [e for c in cohort for e in c["adverse_events"]]
    assert aes, "в когорте должны быть НЯ"
    assert {e["term"] for e in aes} <= set(AE_TERMS)
    assert {e["severity"] for e in aes} <= {"mild", "moderate", "severe"}
    assert all(not e["serious"] or e["severity"] == "severe" for e in aes)


def test_stop_reasons_cover_groups(cohort):
    reasons = {c["stop_reason"] for c in cohort}
    assert {None, "completed", "adverse_event", "inefficacy", "lost_to_followup"} <= reasons
    assert reasons <= {None, "completed", "adverse_event", "inefficacy", "improvement", "switch", "lost_to_followup"}


def test_dates_and_visits_consistent(cohort):
    for c in cohort:
        start = date.fromisoformat(c["start_date"])
        assert start <= TODAY
        weeks = [v["week"] for v in c["visits"]]
        assert weeks[0] == 0 and c["visits"][0]["gad7"] is not None, "исходное измерение есть всегда"
        assert weeks == sorted(weeks) and all(w % 2 == 0 for w in weeks)
        for v in c["visits"]:
            assert v["gad7"] is None or 0 <= v["gad7"] <= 21
            assert v["phq9"] is None or 0 <= v["phq9"] <= 27
        if c["end_date"] is None:
            assert c["stop_reason"] is None
            assert start + timedelta(weeks=max(weeks)) <= TODAY
        else:
            end = date.fromisoformat(c["end_date"])
            assert end <= TODAY and start + timedelta(weeks=max(weeks)) <= end
        assert all(e["week"] <= max(weeks) + 2 for e in c["adverse_events"])


def test_demo_doctor_has_enough_courses(cohort):
    assert sum(c["doctor_id"] == DEMO_DOCTOR for c in cohort) >= 30


def test_report_is_plausible(cohort):
    r = aviandr_report(cohort, {}, "gad7", k_min=5)
    assert r["n"] == 300
    assert 20 <= r["benefit_index"]["value_pct"] <= 80
    cont = [p for p in r["trajectories"]["continued"] if p["week"] == 8][0]
    assert cont["median"] < [p for p in r["trajectories"]["continued"] if p["week"] == 0][0]["median"]
    ineff = [c for c in cohort if outcome_group(c) == "stopped_inefficacy"]
    assert ineff, "должны быть отмены из-за недостаточного эффекта"
