"""Варианты терапии — справочно по действующим КР Минздрава (kompas_core/guidelines/minzdrav.yaml).

Справка подбирается по диагнозу пациента и не является назначением. Для каждого препарата отмечено,
есть ли показание в инструкции; препараты вне зарегистрированного показания помечены off_label —
их применение возможно только по решению врача, система такой вариант не предлагает.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

import yaml

GUIDELINES = Path(__file__).parent / "guidelines" / "minzdrav.yaml"
LINES = {"first": "Первая линия", "second": "Вторая линия", "third": "Третья линия",
         "fourth": "Четвёртая линия", "adjunct": "Дополнительно"}


@lru_cache(maxsize=None)
def _load() -> list:
    with GUIDELINES.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_guidelines() -> list[dict]:
    return copy.deepcopy(_load())


def _icd_match(code: str, allowed: list[str]) -> bool:
    return any(code == a or code.startswith(a + ".") for a in allowed)


def therapy_options(record: dict) -> list[dict]:
    """Справка по КР для диагнозов пациента; диагноз «под вопросом» отмечается отдельно."""
    diagnoses = record.get("diagnoses") or []
    current = {m["mnn"].split(" (")[0].strip().lower() for m in (record.get("therapy") or {}).get("current", [])
               if m.get("mnn")}
    out = []
    for g in load_guidelines():
        matched = [d for d in diagnoses if _icd_match(d.get("code", ""), g["icd10"])]
        if not matched:
            continue
        for o in g["options"]:
            o["line_label"] = LINES[o["line"]]
            for d in o["drugs"]:
                names = {d["mnn"], *d.get("trade_names", [])}
                d["current"] = bool(names & current)
                d["off_label"] = bool(d.get("off_label", False))
        out.append({
            "guideline": {k: g[k] for k in ("id", "title", "year", "status", "developer", "url")},
            "matched_codes": [d["code"] for d in matched],
            "diagnosis_confirmed": any(d.get("status") == "confirmed" for d in matched),
            "monitoring": g["monitoring"].strip(),
            "options": g["options"],
            "note": ("Справка по КР, не назначение. Показания по инструкциям сверены по vidal.ru, маритупирдин "
                     "по ГРЛС. До апробации каждую отметку нужно сверить с ГРЛС. Применение вне зарегистрированного "
                     "показания решает только врач."),
        })
    return out
