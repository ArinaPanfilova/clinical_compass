"""Аналитика применения препарата по курсам терапии."""
import pytest

from kompas_core.analytics import (
    outcome_group, filter_courses, kpis, trajectories, response_rates, adherence,
    safety, benefit_index, composition, wilson, aviandr_report, CAVEAT,
)


def mk(i=0, *, age=40, sex="Ж", indication="F41.1", comorbidities=(), concomitant=(),
       start="2026-05-01", stop=None, visits=((0, 16, 10), (2, 12, 8), (4, 8, 6)),
       intake=(50, 4, 2), aes=(), doctor="doc-a"):
    """Курс с визитами (неделя, GAD-7, PHQ-9) и НЯ (term, severity, serious)."""
    return {
        "course_id": f"C-{i}", "patient_key": f"K-{i}", "doctor_id": doctor, "drug_id": "aviandr",
        "age": age, "sex": sex, "indication": indication,
        "comorbidities": list(comorbidities), "concomitant": list(concomitant),
        "start_date": start, "end_date": None if stop is None else "2026-06-01",
        "planned_weeks": 8, "stop_reason": stop,
        "visits": [{"week": w, "gad7": g, "phq9": p} for w, g, p in visits],
        "intake": {"taken": intake[0], "missed": intake[1], "unknown": intake[2]},
        "adverse_events": [{"term": t, "severity": s, "serious": ser, "week": 1} for t, s, ser in aes],
    }


# ---------- Группы исхода и фильтры ----------

@pytest.mark.parametrize("reason,group", [
    (None, "continued"), ("completed", "continued"), ("adverse_event", "stopped_ae"),
    ("inefficacy", "stopped_inefficacy"), ("switch", "stopped_other"),
    ("improvement", "stopped_other"), ("lost_to_followup", "stopped_other")])
def test_outcome_group(reason, group):
    assert outcome_group(mk(stop=reason)) == group


def test_filter_by_demographics_and_indication():
    cs = [mk(1, age=25, sex="Ж"), mk(2, age=55, sex="М"), mk(3, age=70, sex="Ж", indication="F43.2")]
    assert [c["course_id"] for c in filter_courses(cs, {"sex": "Ж"})] == ["C-1", "C-3"]
    assert [c["course_id"] for c in filter_courses(cs, {"age_min": 50, "age_max": 69})] == ["C-2"]
    assert [c["course_id"] for c in filter_courses(cs, {"indication": "F43.2"})] == ["C-3"]


def test_filter_comorbidity_none_means_empty_list():
    cs = [mk(1), mk(2, comorbidities=["cardiovascular"]), mk(3, comorbidities=["endocrine"])]
    assert [c["course_id"] for c in filter_courses(cs, {"comorbidity": "none"})] == ["C-1"]
    assert [c["course_id"] for c in filter_courses(cs, {"comorbidity": "endocrine"})] == ["C-3"]


def test_filter_concomitant_period_and_doctor():
    cs = [mk(1, start="2026-01-10", doctor="doc-a"), mk(2, start="2026-04-01", concomitant=["antidepressant"], doctor="doc-b")]
    assert [c["course_id"] for c in filter_courses(cs, {"concomitant": "antidepressant"})] == ["C-2"]
    assert [c["course_id"] for c in filter_courses(cs, {"start_from": "2026-03-01"})] == ["C-2"]
    assert [c["course_id"] for c in filter_courses(cs, {"start_to": "2026-03-01"})] == ["C-1"]
    assert [c["course_id"] for c in filter_courses(cs, {"doctor_id": "doc-a"})] == ["C-1"]


def test_filter_ignores_empty_values():
    cs = [mk(1), mk(2)]
    assert len(filter_courses(cs, {"sex": "", "indication": None, "comorbidity": "all"})) == 2
    assert len(filter_courses(cs, None)) == 2


# ---------- KPI ----------

def test_kpis_counts_by_status():
    cs = [mk(1), mk(2), mk(3, stop="completed"), mk(4, stop="adverse_event"),
          mk(5, stop="adverse_event"), mk(6, stop="inefficacy"), mk(7, stop="lost_to_followup")]
    k = kpis(cs)
    assert k["assigned"] == 7 and k["active"] == 2 and k["completed"] == 1 and k["discontinued"] == 4
    assert k["by_reason"]["adverse_event"] == 2 and k["by_reason"]["inefficacy"] == 1
    assert k["by_reason"]["switch"] == 0 and "completed" not in k["by_reason"]


# ---------- Траектории ----------

def test_trajectories_median_and_quartiles_per_group():
    cs = [mk(1, visits=((0, 10, 5), (2, 8, 5))), mk(2, visits=((0, 14, 5), (2, 10, 5))),
          mk(3, visits=((0, 18, 5), (2, None, None))), mk(4, stop="adverse_event", visits=((0, 20, 9),))]
    t = trajectories(cs, "gad7")
    w0 = t["continued"][0]
    assert (w0["week"], w0["n"], w0["median"], w0["q1"], w0["q3"]) == (0, 3, 14, 12, 16)
    w2 = t["continued"][1]
    assert (w2["week"], w2["n"], w2["median"]) == (2, 2, 9)          # пропуск не считается нулём
    assert t["stopped_ae"] == [{"week": 0, "n": 1, "median": 20, "q1": 20, "q3": 20, "hidden": False}]
    assert t["stopped_inefficacy"] == []


def test_trajectories_hide_points_below_k():
    cs = [mk(i, visits=((0, 10 + i, 5),)) for i in range(4)]
    p = trajectories(cs, "gad7", k_min=5)["continued"][0]
    assert p == {"week": 0, "n": None, "median": None, "q1": None, "q3": None, "hidden": True}


# ---------- Ответ, ремиссия, ДИ ----------

def test_wilson_known_values():
    assert wilson(50, 100) == [0.404, 0.596]
    assert wilson(0, 10) == [0.0, 0.278]
    assert wilson(0, 0) is None


def test_response_rates_itt():
    cs = [mk(1, visits=((0, 16, 9), (8, 8, 4))),     # −50 %: ответ, MCID, не ремиссия (8 ≥ 5)
          mk(2, visits=((0, 16, 9), (8, 12, 8))),    # −4: только MCID
          mk(3, visits=((0, 10, 9), (8, 4, 3))),     # −60 %: ответ, MCID, ремиссия
          mk(4, visits=((0, 15, 9),)),               # нет повторного измерения: в знаменателе
          mk(5, visits=((0, None, None), (2, 9, 4)))]  # нет исходного: исключён
    r = response_rates(cs, "gad7")
    assert r["denominator"] == 4
    assert r["response"]["n"] == 2 and r["response"]["pct"] == 50.0
    assert r["mcid"]["n"] == 3
    assert r["remission"]["n"] == 1
    assert r["response"]["ci95"] == wilson(2, 4)


# ---------- Приверженность ----------

def test_adherence_bands_median_unknown():
    cs = [mk(1, intake=(90, 10, 0)), mk(2, intake=(60, 40, 10)), mk(3, intake=(20, 80, 0)),
          mk(4, intake=(0, 0, 5))]
    a = adherence(cs)
    assert a["courses_with_data"] == 3
    assert a["bands"] == {"≥80%": 1, "50–79%": 1, "<50%": 1}
    assert a["median_pct"] == 60.0
    assert a["unknown_share_pct"] == round(100 * 15 / 315, 1)


# ---------- Безопасность ----------

def test_safety_by_term_and_serious():
    cs = [mk(1, aes=[("сонливость", "mild", False), ("головная боль", "moderate", False)]),
          mk(2, aes=[("сонливость", "moderate", False)]),
          mk(3, stop="adverse_event", aes=[("головокружение", "severe", True)]), mk(4)]
    s = safety(cs)
    assert s["with_ae"]["n"] == 3 and s["serious"]["n"] == 1 and s["stopped_due_to_ae"]["n"] == 1
    assert s["by_term"][0] == {"term": "сонливость", "mild": 1, "moderate": 1, "severe": 0, "total": 2}
    assert [r["term"] for r in s["by_term"]] == ["сонливость", "головная боль", "головокружение"]


# ---------- Индекс устойчивой пользы ----------

def test_benefit_index_itt_and_harm_exclusion():
    cs = [mk(1, visits=((0, 16, 9), (8, 6, 4))),                                   # польза
          mk(2, visits=((0, 16, 9), (8, 6, 4)), aes=[("головокружение", "severe", True)]),  # ответ, но серьёзное НЯ
          mk(3, stop="adverse_event", visits=((0, 16, 9), (4, 7, 4))),            # ответ, но отмена из-за НЯ
          mk(4, visits=((0, 16, 9), (8, 14, 8))),                                  # нет ответа
          mk(5, stop="lost_to_followup", visits=((0, 16, 9),))]                    # потерян: без пользы
    b = benefit_index(cs, "gad7")
    assert (b["numerator"], b["denominator"]) == (1, 5)
    assert b["value_pct"] == 20.0 and b["ci95"] == wilson(1, 5)
    assert b["components"] == {"responders": 3, "with_harm": 2}
    assert "все начатые" in b["formula"]


# ---------- Состав выборки ----------

def test_composition_bands():
    cs = [mk(1, age=18), mk(2, age=34, comorbidities=["cardiovascular", "endocrine"]),
          mk(3, age=35, sex="М", concomitant=["antidepressant"]), mk(4, age=65, indication="F43.2")]
    c = composition(cs)
    assert c["age"] == {"18–34": 2, "35–49": 1, "50–64": 0, "65+": 1}
    assert c["sex"] == {"Ж": 3, "М": 1}
    assert c["indication"] == {"F41.1": 3, "F43.2": 1}
    assert c["comorbidity"] == {"none": 3, "cardiovascular": 1, "endocrine": 1}
    assert c["concomitant"] == {"none": 3, "antidepressant": 1}


# ---------- Отчёт и k-анонимность ----------

def test_report_without_k_shows_everything():
    cs = [mk(1), mk(2, stop="switch")]
    r = aviandr_report(cs, {}, "gad7", k_min=1)
    assert r["n"] == 2 and r["suppressed"] is False and r["caveat"] == CAVEAT
    assert r["kpis"]["by_reason"]["switch"] == 1
    for key in ("kpis", "composition", "trajectories", "response", "adherence", "safety", "benefit_index"):
        assert key in r


def test_report_suppressed_below_k():
    r = aviandr_report([mk(i) for i in range(4)], {}, "gad7", k_min=5)
    assert r["suppressed"] is True and r["n"] is None and "5" in r["message"]


def test_report_masks_small_cells_for_researcher():
    cs = [mk(i) for i in range(6)] + [mk(9, stop="switch", aes=[("тошнота", "mild", False)])]
    r = aviandr_report(cs, {}, "gad7", k_min=5)
    assert r["n"] == 7
    assert r["kpis"]["by_reason"]["switch"] is None          # 1 < 5 → скрыто
    assert r["kpis"]["by_reason"]["inefficacy"] == 0          # ноль не раскрывает человека
    assert r["kpis"]["active"] == 6
    assert r["safety"]["with_ae"] == {"n": None, "pct": None, "ci95": None, "hidden": True}
    assert r["safety"]["by_term"][0]["term"] == "тошнота" and r["safety"]["by_term"][0]["total"] is None


def test_report_empty_selection():
    r = aviandr_report([mk(1)], {"sex": "М"}, "gad7", k_min=5)
    assert r["n"] == 0 and r["empty"] is True and r["suppressed"] is False
