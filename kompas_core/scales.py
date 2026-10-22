"""Подсчёт шкал по YAML-паспортам.

Принципы:
* пропуск ≠ 0: пропуски обрабатываются только по правилу паспорта;
* пункт безопасности не восстанавливается никогда;
* результат хранит всё, что нужно для воспроизведения: версию паспорта, ответы, флаги.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

import yaml

SCALES_DIR = Path(__file__).parent / "scales"


class ScaleInputError(ValueError):
    """Некорректный ввод (неверная длина, значение вне диапазона, неверный тип)."""


@lru_cache(maxsize=None)
def load_passport(scale_id: str) -> dict:
    path = SCALES_DIR / f"{scale_id}.yaml"
    if not path.exists():
        raise KeyError(f"Нет паспорта шкалы '{scale_id}'")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def available_scales() -> list[str]:
    return sorted(p.stem for p in SCALES_DIR.glob("*.yaml"))


@dataclass
class ScaleResult:
    scale_id: str
    passport_version: str
    answers: list[Optional[int]]
    total: Optional[int]              # None, если сумма не рассчитывается
    raw_sum: int                      # сумма только отвеченных пунктов
    answered: int
    missing_items: list[int]          # номера пунктов с 1
    prorated: bool
    category: Optional[str]
    category_label: Optional[str]
    safety_item_value: Optional[int]  # None = нет пункта безопасности ИЛИ он пропущен
    safety_item_missing: bool
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def categorize(scale_id: str, total: int) -> tuple[str, str]:
    p = load_passport(scale_id)
    for c in p["categories"]:
        if c["min"] <= total <= c["max"]:
            return c["code"], c["label"]
    raise ScaleInputError(f"{scale_id}: сумма {total} вне диапазона категорий")


def score(scale_id: str, answers: Sequence[Optional[int]]) -> ScaleResult:
    p = load_passport(scale_id)
    n = p["items"]
    lo, hi = p["item_range"]
    if len(answers) != n:
        raise ScaleInputError(f"{scale_id}: ожидается {n} ответов, получено {len(answers)}")

    clean: list[Optional[int]] = []
    for i, a in enumerate(answers, start=1):
        if a is None:
            clean.append(None)
            continue
        if isinstance(a, bool) or not isinstance(a, int):
            raise ScaleInputError(f"{scale_id}: пункт {i} — ожидается целое, получено {a!r}")
        if not lo <= a <= hi:
            raise ScaleInputError(f"{scale_id}: пункт {i}={a} вне диапазона [{lo},{hi}]")
        clean.append(a)

    missing = [i for i, a in enumerate(clean, start=1) if a is None]
    answered = n - len(missing)
    raw_sum = sum(a for a in clean if a is not None)
    rule = p["scoring"]["missing"]
    flags: list[str] = []

    safety_idx = p.get("safety_item")
    safety_missing = bool(safety_idx and safety_idx in missing)
    safety_value = clean[safety_idx - 1] if safety_idx else None

    total: Optional[int]
    prorated = False
    blocked_by_safety = any(i in rule.get("never_impute_items", []) for i in missing)

    if not missing:
        total = raw_sum
    elif blocked_by_safety:
        total = None
        flags.append("safety_item_missing")
    elif len(missing) <= rule["max_missing_for_proration"]:
        total = _round_half_up(raw_sum * n / answered)
        total = min(total, p["total_range"][1])
        prorated = True
        flags.append("prorated")
    else:
        total = None
        flags.append("too_many_missing")

    category = label = None
    if total is not None:
        category, label = categorize(scale_id, total)

    return ScaleResult(
        scale_id=scale_id,
        passport_version=p["version"],
        answers=clean,
        total=total,
        raw_sum=raw_sum,
        answered=answered,
        missing_items=missing,
        prorated=prorated,
        category=category,
        category_label=label,
        safety_item_value=safety_value,
        safety_item_missing=safety_missing,
        flags=flags,
    )
