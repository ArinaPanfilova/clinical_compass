"""Единая точка входа для бэкенда: запись пациента → факты → правила → JSON.

    from kompas_core import evaluate_patient
    result = evaluate_patient(record)        # dict, готовый к отдаче через API

Формат record описан в docs/API_CONTRACT.md.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Optional

from .dynamics import classify_change, trend
from .drugs import check_drug, load_card
from .rules_engine import run_rules, PRIORITIES
from .scales import score
from .text_screen import screen_text

ENGINE_VERSION = "0.1.0"


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(x)


def build_facts(record: dict) -> tuple[dict, dict]:
    """Возвращает (facts, details). facts — плоский словарь для правил; None = неизвестно."""
    facts: dict = {
        "patient.age": record.get("age"),
        "patient.emergency_button": record.get("emergency_button"),
        "selfreport.missed_consecutive": record.get("selfreports_missed_consecutive"),
        "symptoms.mania_or_psychosis": (record.get("symptom_checklist") or {}).get("mania_or_psychosis"),
        "therapy.weeks_on_current": (record.get("therapy") or {}).get("weeks_on_current"),
    }
    details: dict = {"scales": {}, "changes": {}, "trends": {}, "text": []}

    by_scale: dict[str, list] = {}
    for a in sorted(record.get("assessments", []), key=lambda a: _d(a["date"])):
        by_scale.setdefault(a["scale"], []).append(a)

    for sid, items in by_scale.items():
        scored = [(_d(a["date"]), score(sid, a["answers"])) for a in items]
        last_date, last = scored[-1]
        details["scales"][sid] = [{"date": d.isoformat(), **s.to_dict()} for d, s in scored]
        facts[f"{sid}.total"] = last.total
        facts[f"{sid}.category"] = last.category
        facts[f"{sid}.prorated"] = last.prorated
        facts[f"{sid}.too_many_missing"] = "too_many_missing" in last.flags
        if sid == "phq9":
            facts["phq9.item9"] = last.safety_item_value
            facts["phq9.safety_item_missing"] = last.safety_item_missing

        valid = [(d, s.total) for d, s in scored if s.total is not None]
        if len(valid) >= 2 and last.total is not None:
            base = valid[0][1]
            ch = classify_change(sid, base, last.total)
            details["changes"][sid] = ch.to_dict()
            for k in ("direction", "delta", "response", "remission", "baseline"):
                facts[f"{sid}.change.{k}"] = getattr(ch, k)
        details["trends"][sid] = trend([(d, s.total) for d, s in scored],
                                       record.get("expected_interval_days", 14)).to_dict()

    primary = record.get("primary_scale", "phq9")
    facts["primary.change.response"] = facts.get(f"{primary}.change.response")

    # Свободный текст: только записи после последнего просмотра врачом
    flagged = []
    for entry in record.get("diary", []):
        r = screen_text(entry.get("text", ""))
        details["text"].append({"date": entry.get("date"), "flagged": r.flagged,
                                "matched": r.matched, "negated": r.negated})
        flagged += r.matched
    facts["text.concern_flag"] = bool(flagged) if record.get("diary") is not None else None
    facts["text.matched"] = ", ".join(flagged) if flagged else None

    aes = record.get("adverse_events")
    if aes is None:
        facts["ae.serious_reported"] = facts["ae.any_new"] = None
    else:
        new = [e for e in aes if e.get("new", True)]
        facts["ae.any_new"] = bool(new)
        facts["ae.serious_reported"] = any(e.get("serious") for e in new)
        facts["ae.description"] = "; ".join(e.get("description", "") for e in new) or None
    return facts, details


def evaluate_patient(record: dict, drugs: Optional[list[str]] = None,
                     drug_cards: Optional[dict] = None) -> dict:
    t0 = time.perf_counter()
    facts, details = build_facts(record)
    findings = [f.to_dict() for f in run_rules(facts)]

    drug_checks = []
    for drug_id in drugs or []:
        card = (drug_cards or {}).get(drug_id) or load_card(drug_id)
        drug_checks.append(check_drug(card, record).to_dict())

    top = min((PRIORITIES[f["priority"]] for f in findings), default=None)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return {
        "patient_id": record.get("patient_id"),
        "engine_version": ENGINE_VERSION,
        "triage_level": next((k for k, v in PRIORITIES.items() if v == top), "none"),
        "findings": findings,
        "drug_checks": drug_checks,
        "facts": facts,
        "details": details,
        "disclaimer": ("Система поддержки решений. Клинические действия выполняет только врач. "
                       "Отсутствие алерта не означает отсутствие опасности."),
        "elapsed_ms": round(elapsed_ms, 3),
    }
