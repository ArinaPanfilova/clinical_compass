"""Извлечение ключевых сведений из медицинских документов (kompas_core.extraction).

Главное правило: «неизвестно» ≠ «нет». Факт, о котором документ молчит, — None; False только
при явном отрицании. Самая опасная ошибка — False/None там, где противопоказание есть.
"""
import random

import pytest

from evaluation.evaluate_extraction import CONTRAINDICATION_KEYS, evaluate, prf, to_truth_shape
from kompas_core import extract
from kompas_core.extraction import SAFETY_KEYS as EXTRACT_SAFETY_KEYS
from synthetic.documents import (DEV_POOL, POOLS, SAFETY_KEYS, TEMPLATES, _all_strings,
                                 generate_documents, validate_pool)


# --- помощники ---------------------------------------------------------------------------------

def safety(out, key):
    return out["safety"][key]["value"]


def dx(out):
    return {(d["code"], d["status"]) for d in out["diagnoses"]}


def meds(out):
    return {(m["mnn"], m["dose_mg"], m["status"]) for m in out["medications"]}


def allergens(out):
    return None if out["allergies"] is None else sorted(a["name"] for a in out["allergies"])


def evidences(out):
    for group in ("diagnoses", "medications"):
        for item in out[group]:
            yield item["evidence"]
    for item in out["allergies"] or []:
        yield item["evidence"]
    if out.get("allergies_evidence"):
        yield out["allergies_evidence"]
    for v in out["safety"].values():
        if v["evidence"] is not None:
            yield v["evidence"]


# --- формат выхода -----------------------------------------------------------------------------

def test_output_shape_and_unknown_is_none():
    """Документ упоминает только беременность: она False, всё остальное — None, а не False."""
    out = extract("Пациентка К., 30 лет. Беременность исключена.")
    assert out["status"] == "extracted_unverified"
    assert set(out["safety"]) == set(SAFETY_KEYS)
    assert safety(out, "pregnancy") is False
    assert all(out["safety"][k]["value"] is None for k in SAFETY_KEYS if k != "pregnancy")
    assert all(out["safety"][k]["evidence"] is None for k in SAFETY_KEYS if k != "pregnancy")
    assert out["diagnoses"] == [] and out["medications"] == []
    assert out["allergies"] is None


def test_safety_keys_match_generator():
    assert tuple(EXTRACT_SAFETY_KEYS) == SAFETY_KEYS


def test_empty_text():
    out = extract("")
    assert out["status"] == "extracted_unverified"
    assert set(out["safety"]) == set(SAFETY_KEYS)
    assert all(v == {"value": None, "evidence": None} for v in out["safety"].values())
    assert (out["diagnoses"], out["medications"], out["allergies"], out["document_date"]) == ([], [], None, None)


# --- отрицания ---------------------------------------------------------------------------------

def test_explicit_negations():
    out = extract("Эпилепсию отрицает. Беременность исключена. Грудью не кормит. "
                  "Заболевания печени отрицает. Употребление алкоголя и ПАВ отрицает.")
    assert safety(out, "epilepsy_or_organic_brain_lesion") is False
    assert safety(out, "pregnancy") is False
    assert safety(out, "breastfeeding") is False
    assert safety(out, "hepatic_insufficiency") is False
    assert safety(out, "substance_dependence") is False
    assert out["diagnoses"] == []          # отрицаемое не становится диагнозом


def test_negation_covers_list_before_trigger():
    out = extract("Эпилепсию, ЧМТ отрицает. Сахарный диабет, заболевания щитовидной железы отрицает.")
    assert safety(out, "epilepsy_or_organic_brain_lesion") is False
    assert safety(out, "endocrine_disorder") is False


def test_negation_does_not_leak_to_neighbouring_fact():
    out = extract("Беременность 12 недель, эпилепсию отрицает.")
    assert safety(out, "pregnancy") is True
    assert safety(out, "epilepsy_or_organic_brain_lesion") is False
    out = extract("Не беременна, кормит грудью.")
    assert safety(out, "pregnancy") is False
    assert safety(out, "breastfeeding") is True


def test_not_excluded_is_not_negation():
    """«Не исключена» — сомнение, а не отрицание: None, но ни в коем случае не False."""
    out = extract("Беременность не исключена, рекомендован тест. Эпилепсию отрицает.")
    assert safety(out, "pregnancy") is None
    assert safety(out, "epilepsy_or_organic_brain_lesion") is False


def test_family_history_is_not_patient_fact():
    out = extract("Наследственность: эпилепсия у отца, сахарный диабет 2 типа у матери. "
                  "Ишемическая болезнь сердца (I25.9).")
    assert safety(out, "epilepsy_or_organic_brain_lesion") is None
    assert safety(out, "endocrine_disorder") is None
    assert safety(out, "cardiovascular_disease") is True
    assert dx(out) == {("I25.9", "confirmed")}


def test_hypothetical_mentions_are_ignored():
    out = extract("РЕКОМЕНДАЦИИ\nПри планировании беременности — консультация психиатра.\n"
                  "При появлении судорог — срочно обратиться к неврологу.\nКонтроль СКФ через 3 месяца.")
    assert safety(out, "pregnancy") is None
    assert safety(out, "epilepsy_or_organic_brain_lesion") is None
    assert safety(out, "renal_gfr_below_60") is None
    # то же слово без условия — факт
    assert safety(extract("Беременность 9 недель."), "pregnancy") is True


def test_positive_wins_over_negation_elsewhere():
    """Противоречие в документе решается в сторону осторожности: True."""
    out = extract("Заболевания сердечно-сосудистой системы отрицает.\nСопутствующие: ИБС.")
    assert safety(out, "cardiovascular_disease") is True


# --- сокращения --------------------------------------------------------------------------------

def test_referral_abbreviations():
    text = ("Направление на консультацию к психиатру 26.10.26\nПац-ка Т., 28 л.\nDs: ГТР (F41.1)\n"
            "Сопут.: СД 2 т., ГБ II ст., ИБС, ХБП С3а (СКФ 52).\nГВ.\nАллергия: пенициллин.")
    out = extract(text)
    assert dx(out) == {("F41.1", "confirmed"), ("E11.9", "confirmed"), ("I11.9", "confirmed"),
                       ("I25.9", "confirmed"), ("N18.3", "confirmed")}
    assert safety(out, "endocrine_disorder") is True
    assert safety(out, "cardiovascular_disease") is True
    assert safety(out, "renal_gfr_below_60") is True
    assert safety(out, "breastfeeding") is True
    assert allergens(out) == ["пенициллин"]
    assert out["document_date"] == "2026-10-26"


def test_gfr_value_decides_renal_fact():
    assert safety(extract("СКФ 45 мл/мин/1,73 м²."), "renal_gfr_below_60") is True
    assert safety(extract("СКФ 92 мл/мин/1,73 м²."), "renal_gfr_below_60") is False
    out = extract("Сопут.: ХБП С2 (СКФ 78).")
    assert safety(out, "renal_gfr_below_60") is False
    assert ("N18.2", "confirmed") in dx(out)
    assert safety(extract("Сопут.: ХБП С4 (СКФ 22)."), "renal_gfr_below_60") is True


def test_short_negations():
    out = extract("Б-сть: нет. ГВ: нет. иМАО: нет. ССЗ: нет. Эпилепсия: нет.")
    assert safety(out, "pregnancy") is False
    assert safety(out, "breastfeeding") is False
    assert safety(out, "maoi_within_2_weeks") is False
    assert safety(out, "cardiovascular_disease") is False
    assert safety(out, "epilepsy_or_organic_brain_lesion") is False


# --- диагнозы и коды МКБ ---------------------------------------------------------------------

def test_icd_codes_and_status():
    assert dx(extract("Основной: Генерализованное тревожное расстройство (F41.1)")) == {("F41.1", "confirmed")}
    assert dx(extract("Ds: F41.1?")) == {("F41.1", "suspected")}
    assert dx(extract("Основной: Расстройство адаптации (F43.2) под вопросом")) == {("F43.2", "suspected")}
    assert dx(extract("Предварительный диагноз: смешанное тревожное и депрессивное расстройство.")) == {
        ("F41.2", "suspected")}


def test_suspected_marker_does_not_spill_to_comorbid():
    out = extract("ДИАГНОЗ\nОсновной (предварительный): ГТР\nСопутствующие: Сахарный диабет 2 типа (E11.9)")
    assert dx(out) == {("F41.1", "suspected"), ("E11.9", "confirmed")}


def test_diagnosis_name_without_code_maps_to_code():
    out = extract("Страдает гипертонической болезнью II стадии и сахарным диабетом 2 типа. "
                  "Наблюдается у психиатра с диагнозом рекуррентное депрессивное расстройство, "
                  "текущий эпизод средней степени.")
    assert dx(out) == {("I11.9", "confirmed"), ("E11.9", "confirmed"), ("F33.1", "confirmed")}


def test_name_and_code_give_one_diagnosis():
    out = extract("Основной: Расстройство адаптации (F43.2). Сопутствующие: E11.9 Сахарный диабет 2 типа")
    assert sorted(d["code"] for d in out["diagnoses"]) == ["E11.9", "F43.2"]


def test_cyrillic_lookalike_letters_in_code():
    """В русских документах «Е11.9» нередко набирают кириллической Е."""
    out = extract("Сопутствующие: Е11.9")
    assert dx(out) == {("E11.9", "confirmed")}
    assert safety(out, "endocrine_disorder") is True


# --- препараты, дозы, отмены -------------------------------------------------------------------

def test_current_and_cancelled_medications():
    out = extract("Принимает сертралин 50 мг утром. Ранее принимала пароксетин 20 мг, "
                  "отменён 12.09 из-за тошноты.")
    assert meds(out) == {("сертралин", 50, "current"), ("пароксетин", 20, "cancelled")}


def test_trade_names_doses_and_decimal_comma():
    out = extract("ЛЕЧЕНИЕ\nЗолофт 100мг утром.\nВенлафаксин 37,5 мг 2 раза в день.\n"
                  "Алпразолам 0.25 мг на ночь.\nФеназепам 1 мг на ночь.\nМетформин 1000 мг 2 раза в день.")
    assert meds(out) == {("сертралин", 100, "current"), ("венлафаксин", 37.5, "current"),
                         ("алпразолам", 0.25, "current"),
                         ("бромдигидрохлорфенилбензодиазепин", 1, "current")}


def test_referral_therapy_line_with_cancelled_item():
    out = extract("Терапия: Флувоксамин 100 мг 1 р/д; Амитриптилин — отм. 02.08.2026.")
    assert meds(out) == {("флувоксамин", 100, "current"), ("амитриптилин", None, "cancelled")}


def test_continue_recommendation_does_not_duplicate():
    out = extract("ЛЕЧЕНИЕ\nСертралин 50 мг утром.\n\nРЕКОМЕНДАЦИИ\nПродолжить приём сертралина 50 мг утром.")
    assert meds(out) == {("сертралин", 50, "current")}


def test_medication_start_date_is_not_cancellation():
    out = extract("Дата выписки: 26.10.2026\nМоклобемид 300 мг 2 раза в день, принимает с 01.08.2026.")
    assert meds(out) == {("моклобемид", 300, "current")}
    assert safety(out, "maoi_within_2_weeks") is True


@pytest.mark.parametrize("text,expected", [
    ("Дата: 26.10.2026\nМоклобемид 300 мг — отменён 5 дней назад.", True),
    ("Дата: 26.10.2026\nПирлиндол — отменён неделю назад (тошнота).", True),
    ("Дата: 26.10.2026\nМоклобемид 150 мг — отменён месяц назад из-за тошноты.", False),
    ("Дата: 26.10.2026\nСелегилин 5 мг — отменён 20.10 из-за головной боли.", True),     # 6 дней
    ("Дата: 26.10.2026\nСелегилин 5 мг — отменён 12.10.2026 из-за головной боли.", False),  # 14 дней
    ("Дата: 26.10.2026\nСелегилин 5 мг — отменён 13.10.2026.", True),                    # 13 дней
    ("Селегилин 5 мг — отменён 20.10 из-за головной боли.", None),   # нет даты документа
    ("Дата: 26.10.2026\nРанее принимала моклобемид 300 мг, отменён из-за тошноты.", None),  # срок не указан
    ("Ингибиторы МАО не принимает.", False),
    ("Принимает пиразидол 50 мг 2 раза в день.", True),
    ("Принимает сертралин 50 мг.", None),
])
def test_maoi_within_two_weeks(text, expected):
    assert safety(extract(text), "maoi_within_2_weeks") is expected


def test_maoi_cancellation_across_new_year():
    out = extract("Осмотр терапевта от 05.01.2026.\nМоклобемид 300 мг — отменён 28.12 из-за тошноты.")
    assert out["document_date"] == "2026-01-05"
    assert safety(out, "maoi_within_2_weeks") is True        # 8 дней, прошлый год


def test_document_date_formats():
    assert extract("Осмотр терапевта от 11 июля 2026 г.\nЖалоб нет.")["document_date"] == "2026-07-11"
    assert extract("ВЫПИСНОЙ ЭПИКРИЗ\nДата выписки: 29.03.2026")["document_date"] == "2026-03-29"
    assert extract("Жалоб нет.")["document_date"] is None


def test_negated_medication_is_not_extracted():
    out = extract("Антидепрессанты ранее не получала. Авиандр не назначался. Принимает сертралин 25 мг.")
    assert meds(out) == {("сертралин", 25, "current")}


# --- аллергии ----------------------------------------------------------------------------------

def test_allergy_denied_vs_not_mentioned():
    out = extract("АЛЛЕРГОЛОГИЧЕСКИЙ АНАМНЕЗ\nНе отягощён.")
    assert out["allergies"] == []
    assert "отягощ" in out["allergies_evidence"]["quote"]
    out = extract("Аллергию отрицает.")
    assert out["allergies"] == []
    assert extract("Жалобы на тревогу.")["allergies"] is None


def test_allergy_list_and_aliases():
    out = extract("Аллергия на новокаин и анальгин (крапивница). Непереносимость сульфаниламидов.")
    assert allergens(out) == ["метамизол натрия", "прокаин", "сульфаниламиды"]


def test_aviandr_allergy_is_hypersensitivity_not_medication():
    out = extract("Аллергия на Авиандр (сыпь). Принимает сертралин 50 мг.")
    assert allergens(out) == ["авиандр"]
    assert safety(out, "hypersensitivity_aviandr") is True
    assert meds(out) == {("сертралин", 50, "current")}


def test_general_allergy_denial_does_not_deny_aviandr_hypersensitivity():
    """«Аллергию отрицает» — не утверждение о новом препарате: гиперчувствительность остаётся None."""
    out = extract("Аллергию отрицает.")
    assert out["allergies"] == []
    assert safety(out, "hypersensitivity_aviandr") is None
    out = extract("Гиперчувствительности к компонентам Авиандра нет. Аллергию отрицает.")
    assert safety(out, "hypersensitivity_aviandr") is False


def test_lactose_intolerance_is_not_an_allergen():
    out = extract("Непереносимость лактозы. Аллергию отрицает.")
    assert safety(out, "lactose_intolerance") is True
    assert out["allergies"] == []


# --- цитаты ------------------------------------------------------------------------------------

def test_evidence_points_to_source_fragment():
    text = ("Осмотр терапевта от 07.10.2026.\nЭпилепсию отрицает. СКФ 52 мл/мин/1,73 м². "
            "Ранее принимала пароксетин 20 мг, отменён 12.09 из-за тошноты. "
            "Аллергия на пенициллин. Заключение: Генерализованное тревожное расстройство (F41.1).")
    out = extract(text)
    for ev in evidences(out):
        assert text[ev["start"]:ev["end"]] == ev["quote"]
    ep = out["safety"]["epilepsy_or_organic_brain_lesion"]
    assert ep["value"] is False and "Эпилепсию" in ep["evidence"]["quote"] and "отрицает" in ep["evidence"]["quote"]
    assert "52" in out["safety"]["renal_gfr_below_60"]["evidence"]["quote"]
    (par,) = out["medications"]
    assert par["evidence"]["quote"].startswith("пароксетин") and "отменён" in par["evidence"]["quote"]
    (d,) = out["diagnoses"]
    assert d["evidence"]["quote"] == "Генерализованное тревожное расстройство (F41.1)"
    (al,) = out["allergies"]
    assert al["evidence"]["quote"] == "пенициллин"


def test_evidence_on_generated_documents_is_exact():
    n = 0
    for doc in generate_documents(60, 5, "dev"):
        out = extract(doc["text"])
        for ev in evidences(out):
            assert doc["text"][ev["start"]:ev["end"]] == ev["quote"]
            assert ev["quote"].strip()
            n += 1
    assert n > 200


# --- шаблон А: порядок разделов не влияет --------------------------------------------------

def _canonical(shape):
    return {
        "diagnoses": sorted((d["code"], d["status"]) for d in shape["diagnoses"]),
        "medications": sorted((m["mnn"], str(m["dose_mg"]), m["status"]) for m in shape["medications"]),
        "allergies": None if shape["allergies"] is None else sorted(shape["allergies"]),
        "safety": shape["safety"],
    }


def test_template_a_section_order_does_not_change_result():
    docs = [d for d in generate_documents(80, 11, "dev") if d["template"] == "А"][:15]
    assert len(docs) >= 10
    rnd = random.Random(0)
    for doc in docs:
        head, *sections = doc["text"].strip("\n").split("\n\n")
        base = _canonical(to_truth_shape(extract(doc["text"])))
        assert base == _canonical(doc["truth"])
        for _ in range(3):
            rnd.shuffle(sections)
            permuted = head + "\n\n" + "\n\n".join(sections) + "\n"
            assert _canonical(to_truth_shape(extract(permuted))) == base


# --- метрики -----------------------------------------------------------------------------------

def test_prf():
    assert prf(8, 2, 0) == pytest.approx((0.8, 1.0, 8 / 9))
    assert prf(0, 0, 0) == (1.0, 1.0, 1.0)      # нечего находить и ничего не найдено


def test_scoring_counts_errors_and_dangerous_ones():
    truth = {"diagnoses": [{"code": "F41.1", "status": "confirmed"}],
             "medications": [{"mnn": "сертралин", "dose_mg": 50, "status": "current"}],
             "allergies": None,
             "safety": {**{k: None for k in SAFETY_KEYS}, "pregnancy": True,
                        "epilepsy_or_organic_brain_lesion": True, "cardiovascular_disease": True}}
    pred = {"diagnoses": [{"code": "F41.1", "status": "suspected"}, {"code": "E11.9", "status": "confirmed"}],
            "medications": [{"mnn": "сертралин", "dose_mg": 100, "status": "current"}],
            "allergies": [],
            "safety": {**{k: None for k in SAFETY_KEYS}, "pregnancy": False, "cardiovascular_disease": None}}
    docs = [{"doc_id": "x", "template": "А", "text": "", "truth": truth}]
    res = evaluate(docs, lambda _t: pred)
    g = res["groups"]
    assert (g["diagnoses"]["tp"], g["diagnoses"]["fp"], g["diagnoses"]["fn"]) == (0, 2, 1)
    assert (g["medications"]["tp"], g["medications"]["fp"], g["medications"]["fn"]) == (1, 0, 0)
    assert (g["doses"]["tp"], g["doses"]["fp"], g["doses"]["fn"]) == (0, 1, 1)
    assert res["allergy_status"]["accuracy"] == 0.0
    dang = res["dangerous"]
    assert dang["false_at_true"] == 1 and dang["none_at_true"] == 1 and dang["total"] == 2
    assert dang["by_key"]["pregnancy"] == {"false_at_true": 1, "none_at_true": 0}
    assert dang["by_key"]["epilepsy_or_organic_brain_lesion"] == {"false_at_true": 0, "none_at_true": 1}
    assert dang["by_key"]["renal_gfr_below_60"] == {"false_at_true": 0, "none_at_true": 0}
    assert res["cautions_missed"]["cardiovascular_disease"] == {"false_at_true": 0, "none_at_true": 1}
    assert res["safety"]["pregnancy"]["confusion"]["True"]["False"] == 1
    assert set(res["by_template"]) == {"А"}


def test_contraindication_keys_come_from_aviandr_card():
    assert set(CONTRAINDICATION_KEYS) == {
        "hypersensitivity_aviandr", "epilepsy_or_organic_brain_lesion", "maoi_within_2_weeks",
        "renal_gfr_below_60", "hepatic_insufficiency", "pregnancy", "breastfeeding"}


# --- генератор документов ------------------------------------------------------------------

def test_generator_is_deterministic_and_covers_templates():
    a = generate_documents(90, 3, "dev")
    assert a == generate_documents(90, 3, "dev")
    assert {d["template"] for d in a} == set(TEMPLATES)
    for d in a:
        assert set(d["truth"]) == {"diagnoses", "medications", "allergies", "safety"}
        assert set(d["truth"]["safety"]) == set(SAFETY_KEYS)
        assert "{" not in d["text"] and "}" not in d["text"]


def test_generator_covers_required_phenomena():
    docs = generate_documents(300, 42, "dev")
    T = [d["truth"] for d in docs]
    assert {x["status"] for t in T for x in t["diagnoses"]} == {"confirmed", "suspected"}
    assert {x["status"] for t in T for x in t["medications"]} == {"current", "cancelled"}
    assert any(t["allergies"] == [] for t in T) and any(t["allergies"] is None for t in T)
    assert any(t["allergies"] for t in T)
    for key in SAFETY_KEYS:
        assert {t["safety"][key] for t in T} == {True, False, None}, key
    assert any("у матери" in d["text"] or "у отца" in d["text"] for d in docs)   # чужой анамнез
    assert any(t["diagnoses"][0]["code"] not in d["text"] for d, t in zip(docs, T))  # диагноз без кода


def test_test_pool_is_held_out_paraphrase():
    assert "test" in POOLS, "отложенный пул test не написан"
    assert validate_pool(POOLS["test"]) == []
    dev = set(_all_strings(DEV_POOL))
    test = list(_all_strings(POOLS["test"]))
    assert sum(s not in dev for s in test) / len(test) >= 0.7
    # содержание (эталон) не зависит от пула — отличаются только формулировки
    a, b = generate_documents(40, 9, "dev"), generate_documents(40, 9, "test")
    assert [d["truth"] for d in a] == [d["truth"] for d in b]
    assert sum(x["text"] != y["text"] for x, y in zip(a, b)) >= 38


# --- главный критерий на пуле разработки ---------------------------------------------------

@pytest.fixture(scope="module")
def dev_metrics():
    return evaluate(generate_documents(300, 42, "dev"), extract)


@pytest.mark.parametrize("group", ["diagnoses", "medications", "doses", "allergies"])
def test_dev_pool_f1_per_group(dev_metrics, group):
    assert dev_metrics["groups"][group]["f1"] >= 0.95, dev_metrics["groups"][group]


@pytest.mark.parametrize("key", SAFETY_KEYS)
def test_dev_pool_f1_per_safety_fact(dev_metrics, key):
    assert dev_metrics["safety"][key]["macro_f1"] >= 0.95, dev_metrics["safety"][key]


def test_dev_pool_allergy_status(dev_metrics):
    assert dev_metrics["allergy_status"]["accuracy"] >= 0.95


def test_dev_pool_no_dangerous_errors(dev_metrics):
    assert dev_metrics["dangerous"]["total"] == 0, dev_metrics["dangerous"]["examples"][:5]
