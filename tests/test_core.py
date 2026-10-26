import itertools
import math

import pytest

from kompas_core import (score, classify_change, reliable_change_threshold, run_rules,
                         load_rules, check_auto_actions, check_drug, load_card,
                         screen_text, evaluate_patient)
from kompas_core.rules_engine import evaluate, UNKNOWN
from kompas_core.scales import ScaleInputError, categorize


def answers_with_total(n_items, total, last_zero=False):
    """Строит набор ответов 0..3 с заданной суммой (п.9 = 0, если last_zero)."""
    a = [0] * n_items
    rng = range(n_items - 1) if last_zero else range(n_items)
    rest = total
    for i in rng:
        a[i] = min(3, rest)
        rest -= a[i]
    assert rest == 0
    return a


# ---------- Шкалы ----------

@pytest.mark.parametrize("total,cat", [
    (0, "minimal"), (4, "minimal"), (5, "mild"), (9, "mild"), (10, "moderate"),
    (14, "moderate"), (15, "moderately_severe"), (19, "moderately_severe"),
    (20, "severe"), (27, "severe")])
def test_phq9_category_boundaries(total, cat):
    assert score("phq9", answers_with_total(9, total)).category == cat


@pytest.mark.parametrize("total,cat", [
    (0, "minimal"), (4, "minimal"), (5, "mild"), (9, "mild"),
    (10, "moderate"), (14, "moderate"), (15, "severe"), (21, "severe")])
def test_gad7_category_boundaries(total, cat):
    assert score("gad7", answers_with_total(7, total)).category == cat


def test_every_possible_total_has_exactly_one_category():
    for sid, mx in (("phq9", 27), ("gad7", 21)):
        for t in range(mx + 1):
            categorize(sid, t)


def test_phq9_exhaustive_sum_on_random_answers():
    import random
    rnd = random.Random(0)
    for _ in range(5000):
        a = [rnd.randint(0, 3) for _ in range(9)]
        r = score("phq9", a)
        assert r.total == sum(a) and not r.prorated and r.safety_item_value == a[8]


def test_phq9_proration_one_and_two_missing():
    r = score("phq9", [3, 3, 3, 3, 3, 3, 3, None, 0])
    assert r.prorated and r.total == round(21 * 9 / 8)    # 23.625 → 24
    r = score("phq9", [1, 1, 1, 1, 1, 1, None, None, 1])
    assert r.prorated and r.total == 9


def test_phq9_three_missing_not_scored():
    r = score("phq9", [1, 1, 1, 1, 1, 1, None, None, None])
    assert r.total is None and r.category is None


def test_phq9_safety_item_never_imputed():
    r = score("phq9", [3, 3, 3, 3, 3, 3, 3, 3, None])
    assert r.total is None and r.safety_item_missing and "safety_item_missing" in r.flags


def test_gad7_missing_policy():
    assert score("gad7", [2, 2, 2, 2, 2, 2, None]).total == 14
    assert score("gad7", [2, 2, 2, 2, 2, None, None]).total is None


def test_proration_never_exceeds_max():
    r = score("phq9", [3, 3, 3, 3, 3, 3, 3, None, 3])
    assert r.total == 27


@pytest.mark.parametrize("bad", [
    [0] * 8, [0] * 10, [4] + [0] * 8, [-1] + [0] * 8, ["2"] + [0] * 8,
    [True] + [0] * 8, [1.0] + [0] * 8])
def test_invalid_input_rejected(bad):
    with pytest.raises(ScaleInputError):
        score("phq9", bad)


# ---------- Динамика ----------

def test_change_mcid_boundary():
    assert classify_change("phq9", 10, 15).direction == "worsened"
    assert classify_change("phq9", 10, 14).direction == "no_meaningful_change"
    assert classify_change("phq9", 15, 10).direction == "improved"
    assert classify_change("gad7", 10, 14).direction == "worsened"
    assert classify_change("gad7", 10, 13).direction == "no_meaningful_change"


def test_reliable_change_uses_mdc95():
    assert classify_change("phq9", 10, 15).reliable is False     # 5 ≤ 5.72
    assert classify_change("phq9", 10, 16).reliable is True
    assert classify_change("gad7", 10, 16).reliable is None      # порог не задан


def test_response_and_remission():
    c = classify_change("phq9", 20, 10)
    assert c.response and not c.remission
    c = classify_change("phq9", 12, 4)
    assert c.response and c.remission
    assert not classify_change("phq9", 0, 0).response


def test_rci_formula():
    thr = reliable_change_threshold(sd=5.0, reliability=0.84)
    assert math.isclose(thr, 1.96 * 5 * math.sqrt(2) * 0.4, rel_tol=1e-9)


# ---------- Трёхзначная логика ----------

def test_kleene_logic():
    t = {"fact": "a", "op": "==", "value": 1}
    f = {"fact": "b", "op": "==", "value": 1}
    u = {"fact": "missing", "op": "==", "value": 1}
    facts = {"a": 1, "b": 0}
    assert evaluate({"all": [t, u]}, facts) is UNKNOWN
    assert evaluate({"all": [f, u]}, facts) is False
    assert evaluate({"any": [t, u]}, facts) is True
    assert evaluate({"any": [f, u]}, facts) is UNKNOWN
    assert evaluate({"not": u}, facts) is UNKNOWN
    with pytest.raises(TypeError):
        bool(UNKNOWN)


# ---------- Правила ----------

def test_rules_load_and_have_sources_and_safe_actions():
    rules = load_rules()
    assert len(rules) >= 15
    check_auto_actions(rules)
    for r in rules:
        assert r["sources"], r["id"]


def _ids(findings):
    return {f.rule_id for f in findings}


def test_item9_fires_regardless_of_total():
    facts = {"phq9.item9": 1, "phq9.total": 1, "phq9.safety_item_missing": False}
    assert "SAFE-003" in _ids(run_rules(facts))
    facts["phq9.item9"] = 3
    out = run_rules(facts)
    assert "SAFE-002" in _ids(out) and "SAFE-003" not in _ids(out)
    f = next(x for x in out if x.rule_id == "SAFE-002")
    assert f.routing == "mandatory" and f.priority == "urgent"


def test_no_safety_alert_when_item9_zero():
    facts = {"phq9.item9": 0, "phq9.total": 3, "phq9.safety_item_missing": False}
    assert not any(f.kind == "alert" for f in run_rules(facts))


def test_every_finding_requires_doctor():
    facts = {"phq9.item9": 3, "phq9.total": 25, "patient.emergency_button": True,
             "ae.serious_reported": True, "ae.any_new": True}
    out = run_rules(facts)
    assert out and all(f.requires_doctor_confirmation for f in out)
    assert out[0].priority == "emergency"     # сортировка по срочности


def test_mandatory_and_desirable_are_distinct():
    m = run_rules({"phq9.total": 21})
    d = run_rules({"phq9.total": 16})
    assert any(f.routing == "mandatory" for f in m)
    assert any(f.routing == "desirable" for f in d) and not any(f.routing == "mandatory" for f in d)


def test_message_placeholders_filled():
    out = run_rules({"phq9.total": 22})
    msg = next(f.message for f in out if f.rule_id == "ROUT-001")
    assert "22" in msg and "{" not in msg


# ---------- Препарат ----------

TEST_CARD = {
    "id": "testdrug", "trade_name": "Тестпрепарат", "verified": True,
    "registration": {"number": "TEST"}, "instruction_version_date": "2026-01-01",
    "indications_icd10": ["F41.1"], "age_range": {"min": 18, "max": 65},
    "contraindications": [{"id": "CI-1", "fact": "safety.pregnancy", "label": "Беременность"}],
    "cautions": [], "interactions": [],
}


def _pt(**kw):
    base = {"age": 30, "diagnoses": [{"code": "F41.1", "status": "confirmed"}],
            "safety_profile": {"pregnancy": False}, "therapy": {"current": []}}
    base.update(kw)
    return base


def test_unverified_card_never_suggests():
    card = {**TEST_CARD, "verified": False, "verification_level": "none"}
    assert check_drug(card, _pt()).status == "card_not_verified"


def test_secondary_source_card_warns():
    r = check_drug({**load_card("aviandr"), "verification_level": "secondary"}, _pt(safety_profile={}))
    assert r.verification_level == "secondary" and r.warnings
    assert r.status == "insufficient_data"          # профиль безопасности пуст → не «можно»


def test_aviandr_card_reconciled_with_grls_but_awaits_clinical_signoff():
    """Карточка сверена командой с листком-вкладышем ГРЛС; подпись клинического лида — отдельно."""
    card = load_card("aviandr")
    assert card["mnn"] == "маритупирдин"
    assert card["verification_level"] == "grls_team_checked"
    assert "grls.rosminzdrav.ru" in card["registration"]["grls_url"]
    contraindicated = {i["mnn"] for i in card["interactions"] if i["level"] == "contraindicated"}
    assert {"моклобемид", "фенелзин", "транилципромин", "разагилин"} <= contraindicated
    assert "кетоконазол" not in {i["mnn"] for i in card["interactions"]}      # в инструкции ГРЛС нет
    r = check_drug(card, _pt(safety_profile={}))
    assert any("ГРЛС" in w and "клинического лида" in w for w in r.warnings)
    assert "ГРЛС" in r.source


AVIANDR_SAFE = dict(hypersensitivity_aviandr=False, epilepsy_or_organic_brain_lesion=False,
                    maoi_within_2_weeks=False, renal_gfr_below_60=False, hepatic_insufficiency=False,
                    pregnancy=False, breastfeeding=False, cardiovascular_disease=False,
                    endocrine_disorder=False, substance_dependence=False, lactose_intolerance=False,
                    drives_vehicles=False)


def test_aviandr_scenarios():
    card = load_card("aviandr")
    assert check_drug(card, _pt(safety_profile=AVIANDR_SAFE)).status == "can_be_considered"
    assert check_drug(card, _pt(safety_profile={**AVIANDR_SAFE, "epilepsy_or_organic_brain_lesion": True})).status == "not_applicable"
    # депрессия без тревожного показания — не показан (сценарий 3)
    assert check_drug(card, _pt(diagnoses=[{"code": "F32.1", "status": "confirmed"}], safety_profile=AVIANDR_SAFE)).status == "not_applicable"
    # расстройство адаптации: нужно подтверждение пост-COVID контекста
    p = _pt(diagnoses=[{"code": "F43.2", "status": "confirmed"}], safety_profile=AVIANDR_SAFE)
    assert check_drug(card, p).status == "insufficient_data"
    p["context"] = {"post_covid": True, "mild_to_moderate": True}
    assert check_drug(card, p).status == "can_be_considered"
    # МАО-ингибитор в текущей терапии
    p = _pt(safety_profile=AVIANDR_SAFE, therapy={"current": [{"mnn": "Моклобемид"}]})
    assert check_drug(card, p).status == "not_applicable"
    p = _pt(safety_profile=AVIANDR_SAFE, therapy={"current": [{"mnn": "сертралин"}]})
    r = check_drug(card, p)
    assert r.status == "can_be_considered" and r.interactions


def test_drug_statuses():
    assert check_drug(TEST_CARD, _pt()).status == "can_be_considered"
    assert check_drug(TEST_CARD, _pt(safety_profile={"pregnancy": True})).status == "not_applicable"
    assert check_drug(TEST_CARD, _pt(safety_profile={})).status == "insufficient_data"
    assert check_drug(TEST_CARD, _pt(diagnoses=[{"code": "F32.1", "status": "confirmed"}])).status == "not_applicable"
    assert check_drug(TEST_CARD, _pt(diagnoses=[{"code": "F41.1", "status": "suspected"}])).status == "insufficient_data"
    assert check_drug(TEST_CARD, _pt(age=17)).status == "not_applicable"
    assert check_drug(TEST_CARD, _pt(age=None)).status == "insufficient_data"


def test_high_depression_score_does_not_make_drug_applicable():
    # Сценарий 3 из проектного документа
    p = _pt(diagnoses=[], assessments=[{"date": "2026-10-01", "scale": "phq9", "answers": [3] * 8 + [0]}])
    assert check_drug(TEST_CARD, p).status == "not_applicable"


# ---------- Текст ----------

@pytest.mark.parametrize("text", ["Иногда думаю, что не хочу жить", "Хочется умереть",
                                  "мысли причинить себе вред", "Не вижу выхода"])
def test_text_positive(text):
    assert screen_text(text).flagged


@pytest.mark.parametrize("text", ["Мыслей о суициде нет", "Никогда не думала причинить себе вред",
                                  "Сегодня гуляла, настроение лучше", ""])
def test_text_negative(text):
    assert not screen_text(text).flagged


# ---------- Пайплайн ----------

def test_pipeline_end_to_end():
    rec = {
        "patient_id": "p1", "age": 34, "primary_scale": "phq9",
        "assessments": [
            {"date": "2026-09-01", "scale": "phq9", "answers": [2, 2, 1, 1, 1, 1, 1, 1, 0]},
            {"date": "2026-09-15", "scale": "phq9", "answers": [3, 3, 2, 2, 2, 2, 2, 1, 1]},
        ],
        "diary": [], "adverse_events": [], "selfreports_missed_consecutive": 0,
        "emergency_button": False, "symptom_checklist": {"mania_or_psychosis": False},
    }
    out = evaluate_patient(rec, drugs=["aviandr"])
    ids = {f["rule_id"] for f in out["findings"]}
    assert {"SAFE-003", "ROUT-002", "ROUT-004"} <= ids
    assert out["triage_level"] == "urgent"
    assert out["drug_checks"][0]["status"] in {"not_applicable", "insufficient_data"}
    assert out["details"]["changes"]["phq9"]["delta"] == 8


def test_every_rule_fact_is_produced_by_pipeline():
    """Опечатка в имени факта сделала бы правило вечно UNKNOWN — то есть молча мёртвым."""
    from kompas_core.pipeline import build_facts
    from kompas_core.rules_engine import _collect_facts
    rec = {
        "age": 40, "primary_scale": "phq9", "emergency_button": False,
        "assessments": [
            {"date": "2026-09-01", "scale": "phq9", "answers": [1] * 9},
            {"date": "2026-09-15", "scale": "phq9", "answers": [2] * 9},
            {"date": "2026-09-01", "scale": "gad7", "answers": [1] * 7},
            {"date": "2026-09-15", "scale": "gad7", "answers": [2] * 7},
        ],
        "diary": [{"date": "2026-09-15", "text": "ok"}], "adverse_events": [],
        "selfreports_missed_consecutive": 0, "symptom_checklist": {"mania_or_psychosis": False},
        "therapy": {"current": [], "weeks_on_current": 4},
    }
    facts, _ = build_facts(rec)
    used = set()
    for r in load_rules():
        _collect_facts(r["when"], used)
    missing = {f for f in used if f not in facts}
    assert not missing, f"Правила ссылаются на несуществующие факты: {missing}"


# ---------- Производительность: карточка препарата читается один раз ----------

def test_drug_card_parsed_once_and_copies_are_independent(monkeypatch):
    import yaml
    from kompas_core import drugs
    drugs._load_card_file.cache_clear()
    calls = []
    real = yaml.safe_load
    monkeypatch.setattr(yaml, "safe_load", lambda f: calls.append(1) or real(f))
    a = load_card("aviandr")
    a["verification_level"] = "испорчено"
    b = load_card("aviandr")
    assert len(calls) == 1
    assert b["verification_level"] != "испорчено"


def test_insufficient_data_reason_is_human_readable():
    """В тексте для врача — названия из инструкции, а не служебные ключи; ключи остаются в unknown_facts."""
    r = check_drug(load_card("aviandr"), _pt(safety_profile={"pregnancy": False}))
    reason = next(x for x in r.reasons if x.startswith("Не хватает данных"))
    assert "safety." not in reason
    assert "Эпилепсия или органическое поражение головного мозга" in reason
    assert "safety.epilepsy_or_organic_brain_lesion" in r.unknown_facts
