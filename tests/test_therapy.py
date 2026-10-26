"""Справка по вариантам терапии из действующих КР Минздрава: по диагнозу, с источником и отметкой показания."""
from kompas_core.therapy import load_guidelines, therapy_options


def rec(code, status="confirmed", current=()):
    return {"diagnoses": [{"code": code, "status": status}],
            "therapy": {"current": [{"mnn": m} for m in current]}}


def test_guidelines_are_current_minzdrav_documents():
    g = {x["id"]: x for x in load_guidelines()}
    assert set(g) == {"457_3", "301_3"}
    for x in g.values():
        assert x["url"].startswith("https://cr.minzdrav.gov.ru/") and x["year"] == 2024
        assert all(o["source"] for o in x["options"])


def test_gad_options_with_lines_and_evidence():
    [r] = therapy_options(rec("F41.1"))
    assert r["guideline"]["id"] == "457_3"
    ssri = next(o for o in r["options"] if o["label"] == "СИОЗС")
    assert ssri["line"] == "first" and "эсциталопрам" in [d["mnn"] for d in ssri["drugs"]]
    assert ssri["evidence"] == "УУР A, УДД 1"


def test_aviandr_is_third_line_in_gad_guideline():
    [r] = therapy_options(rec("F41.1"))
    third = next(o for o in r["options"] if any(d["mnn"] == "маритупирдин" for d in o["drugs"]))
    assert third["line"] == "third"
    assert "УУР B, УДД 2" in third["evidence"]


def test_off_label_drugs_are_marked():
    """Сертралин при ГТР в КР помечен «#»: показания ГТР в инструкции нет — решение только врача."""
    [r] = therapy_options(rec("F41.1"))
    ssri = next(o for o in r["options"] if o["label"] == "СИОЗС")
    sert = next(d for d in ssri["drugs"] if d["mnn"] == "сертралин")
    assert sert["off_label"] is True
    assert next(d for d in ssri["drugs"] if d["mnn"] == "пароксетин")["off_label"] is False


def test_current_therapy_is_flagged():
    [r] = therapy_options(rec("F41.1", current=["Сертралин"]))
    ssri = next(o for o in r["options"] if o["label"] == "СИОЗС")
    assert next(d for d in ssri["drugs"] if d["mnn"] == "сертралин")["current"] is True


def test_depression_and_suspected_diagnosis():
    [r] = therapy_options(rec("F32.1", status="suspected"))
    assert r["guideline"]["id"] == "301_3" and r["diagnosis_confirmed"] is False


def test_no_guideline_for_other_codes():
    assert therapy_options(rec("F43.2")) == []
    assert therapy_options({"diagnoses": []}) == []
