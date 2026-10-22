"""Анализ динамики: клинически значимое и надёжное изменение, ответ, ремиссия, тренд.

Методологические оговорки (выводятся в интерфейс):
* классификация изменения — описание ряда наблюдений, не вывод о причине (лечение,
  естественное течение, регрессия к среднему неразличимы без контроля);
* повторные анкеты с 14-дневным окном перекрываются, если выдавать их чаще;
* пропуски не интерпретируются как стабильность.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional, Sequence

from .scales import load_passport


def reliable_change_threshold(sd: float, reliability: float, z: float = 1.96) -> float:
    """Порог надёжного изменения Jacobson–Truax: z · SD · √2 · √(1 − r)."""
    if not (0 < reliability < 1) or sd <= 0:
        raise ValueError("Нужны SD > 0 и 0 < r < 1")
    return z * sd * math.sqrt(2) * math.sqrt(1 - reliability)


@dataclass
class ChangeResult:
    scale_id: str
    baseline: int
    current: int
    delta: int                    # current − baseline; >0 = ухудшение
    meaningful: bool              # |delta| ≥ MCID
    reliable: Optional[bool]      # |delta| > MDC95 / RCI, None если порог неизвестен
    direction: str                # improved | worsened | no_meaningful_change
    response: bool                # снижение ≥ 50 %
    remission: bool               # current < порога ремиссии
    thresholds: dict
    caveat: str

    def to_dict(self) -> dict:
        return asdict(self)


def classify_change(scale_id: str, baseline: int, current: int,
                    rci_threshold: Optional[float] = None) -> ChangeResult:
    ch = load_passport(scale_id)["change"]
    delta = current - baseline
    mcid = ch["mcid_points"]
    meaningful = abs(delta) >= mcid

    thr = rci_threshold if rci_threshold is not None else ch.get("mdc95_points")
    reliable = None if thr is None else abs(delta) > thr

    if meaningful and delta < 0:
        direction = "improved"
    elif meaningful and delta > 0:
        direction = "worsened"
    else:
        direction = "no_meaningful_change"

    response = baseline > 0 and (baseline - current) >= ch["response_reduction_fraction"] * baseline
    remission = current < ch["remission_below"]
    return ChangeResult(
        scale_id=scale_id, baseline=baseline, current=current, delta=delta,
        meaningful=meaningful, reliable=reliable, direction=direction,
        response=bool(response), remission=remission,
        thresholds={"mcid": mcid, "reliable_change": thr,
                    "mcid_source": ch["mcid_source"]},
        caveat=ch.get("caveat", "").strip(),
    )


@dataclass
class TrendResult:
    n_points: int
    slope_per_week: Optional[float]   # МНК-наклон, баллы в неделю
    coverage: float                   # доля ожидаемых анкет, которые реально пришли
    max_gap_days: Optional[int]
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def trend(points: Sequence[tuple[date, Optional[int]]], expected_interval_days: int = 14) -> TrendResult:
    """Наклон по МНК только по наблюдённым точкам + явная метрика полноты наблюдения."""
    obs = sorted((d, v) for d, v in points if v is not None)
    if not points:
        return TrendResult(0, None, 0.0, None, "Нет данных")
    all_dates = sorted(d for d, _ in points)
    span = (all_dates[-1] - all_dates[0]).days
    expected = max(1, span // expected_interval_days + 1)
    coverage = min(1.0, len(obs) / expected)

    gaps = [(b[0] - a[0]).days for a, b in zip(obs, obs[1:])]
    max_gap = max(gaps) if gaps else None

    if len(obs) < 3:
        return TrendResult(len(obs), None, coverage, max_gap,
                           "Менее 3 наблюдений: тренд не оценивается")
    t0 = obs[0][0]
    xs = [(d - t0).days / 7 for d, _ in obs]
    ys = [v for _, v in obs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = None if sxx == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    note = "Описательный тренд; не является оценкой эффекта лечения"
    if coverage < 0.7:
        note += ". Полнота наблюдения снижена — стабильность не предполагается"
    return TrendResult(len(obs), slope, round(coverage, 3), max_gap, note)
