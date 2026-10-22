"""Проверка применимости препарата по карточке из ГРЛС.

Возможные статусы (рекомендации «назначить» система не выдаёт никогда):
* card_not_verified   — карточка не заполнена (verification_level: none) → ничего не предлагаем;
* not_applicable      — нет зарегистрированного показания ИЛИ есть противопоказание;
* insufficient_data   — показание/противопоказание нельзя проверить: нет данных;
* can_be_considered   — в пределах зарегистрированных условий; решение за врачом.

Off-label: система не предлагает. Если врач решит иначе — это его действие с обоснованием
в журнале, а не обход проверки.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import yaml

DRUGS_DIR = Path(__file__).parent / "drugs"


def load_card(drug_id: str, drugs_dir: Path = DRUGS_DIR) -> dict:
    with (Path(drugs_dir) / f"{drug_id}.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class DrugCheck:
    drug_id: str
    trade_name: str
    status: str
    reasons: list[str] = field(default_factory=list)
    unknown_facts: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    interactions: list[str] = field(default_factory=list)
    source: str = ""
    verification_level: str = "none"
    warnings: list[str] = field(default_factory=list)
    requires_doctor_confirmation: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _icd_match(code: str, allowed: list[str]) -> bool:
    # F41.1 совпадает с F41.1 и с родительским F41, если показание указано рубрикой
    return any(code == a or code.startswith(a + ".") for a in allowed)


def check_drug(card: dict, patient: dict) -> DrugCheck:
    reg = card.get("registration", {})
    level = card.get("verification_level", "grls_verified" if card.get("verified") else "none")
    src = f"Инструкция, РУ {reg.get('number')}, ред. {card.get('instruction_version_date')}"
    res = DrugCheck(card["id"], card["trade_name"], "can_be_considered", source=src,
                    verification_level=level)

    if level == "none":
        res.status = "card_not_verified"
        res.reasons.append("Карточка препарата не заполнена по инструкции — предложение не формируется")
        return res
    if level == "secondary":
        res.warnings.append("Сведения о препарате из вторичного источника, не сверены с ГРЛС")

    blocking, unknown = [], []
    ctx = {**patient.get("context", {}), **{f"safety.{k}": v for k, v in patient.get("safety_profile", {}).items()}}

    # 1. Показание: подтверждённый диагноз в пределах зарегистрированных показаний
    indications = card.get("indications") or [
        {"id": "IND", "label": "", "icd10": card.get("indications_icd10", []), "requires_true": []}]
    confirmed = [d["code"] for d in patient.get("diagnoses", []) if d.get("status") == "confirmed"]
    suspected = [d["code"] for d in patient.get("diagnoses", []) if d.get("status") != "confirmed"]
    ind_status = "none"
    for ind in indications:
        if any(_icd_match(c, ind["icd10"]) for c in confirmed):
            req = [ctx.get(f) if f.startswith("safety.") else patient.get("context", {}).get(f.removeprefix("context."))
                   for f in ind.get("requires_true", [])]
            if all(v is True for v in req):
                ind_status = "met"
                break
            if any(v is None for v in req) and not any(v is False for v in req):
                ind_status = "unknown"
                unknown += [f for f, v in zip(ind.get("requires_true", []), req) if v is None]
        elif any(_icd_match(c, ind["icd10"]) for c in suspected) and ind_status == "none":
            ind_status = "unknown"
            unknown.append("diagnosis.confirmed")
    if ind_status == "none":
        blocking.append("Нет подтверждённого диагноза в пределах зарегистрированных показаний")
    elif ind_status == "unknown":
        res.reasons.append("Соответствие зарегистрированному показанию не подтверждено")

    # 2. Возраст
    age, rng = patient.get("age"), card.get("age_range") or {}
    if age is None:
        unknown.append("patient.age")
    else:
        if rng.get("min") is not None and age < rng["min"]:
            blocking.append(f"Возраст {age} < {rng['min']} (инструкция)")
        if rng.get("max") is not None and age > rng["max"]:
            blocking.append(f"Возраст {age} > {rng['max']} (инструкция)")

    # 3. Противопоказания: неизвестно ≠ отсутствует
    safety = patient.get("safety_profile", {})
    for ci in card.get("contraindications", []):
        key = ci["fact"].removeprefix("safety.")
        val = safety.get(key)
        if val is True:
            blocking.append(f"Противопоказание: {ci['label']}")
        elif val is None:
            unknown.append(ci["fact"])

    for c in card.get("cautions", []):
        key = c["fact"].removeprefix("safety.")
        if safety.get(key) is True:
            res.cautions.append(c["label"])
        elif safety.get(key) is None:
            unknown.append(c["fact"])

    current = {m["mnn"].lower() for m in patient.get("therapy", {}).get("current", []) if m.get("mnn")}
    for it in card.get("interactions", []):
        if it["mnn"].lower() in current:
            res.interactions.append(f"{it['mnn']}: {it['effect']}")
            if it.get("level") == "contraindicated":
                blocking.append(f"Противопоказанная комбинация с {it['mnn']}")

    res.unknown_facts = sorted(set(unknown))
    if blocking:
        res.status = "not_applicable"
        res.reasons = blocking + res.reasons
    elif unknown:
        res.status = "insufficient_data"
        res.reasons.append("Не хватает данных для проверки: " + ", ".join(res.unknown_facts))
    else:
        res.reasons.append("В пределах зарегистрированных показаний; противопоказаний в профиле не выявлено")
    return res
