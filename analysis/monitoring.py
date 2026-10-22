"""Динамика по продольным данным (например, 14-дневный датасет Kaggle).

    python analysis/monitoring.py data/kaggle.csv --id user_id --time day --score phq9_total
    # или с пунктами:
    python analysis/monitoring.py data/kaggle.csv --id user_id --time day --items "phq1,...,phq9"

Что считает по каждому участнику:
* число наблюдений и полноту (coverage), максимальный разрыв;
* МНК-наклон (баллы/неделю) — описательно;
* пересечение MCID между первым и последним наблюдением.

ВАЖНО о методологии: PHQ-9 спрашивает о последних 14 днях. Если в датасете анкета
заполнялась ежедневно, это НЕ стандартное применение шкалы: соседние ответы перекрываются
по периоду и не являются независимыми наблюдениями. Такие данные годятся для демонстрации
интерфейса мониторинга, но не для оценки чувствительности к изменению.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kompas_core import classify_change, score  # noqa: E402


def per_person(g: pd.DataFrame, time_col: str, score_col: str, expected_days: int) -> dict:
    g = g.sort_values(time_col)
    t = pd.to_numeric(g[time_col], errors="coerce") if not np.issubdtype(g[time_col].dtype, np.datetime64) \
        else (g[time_col] - g[time_col].min()).dt.days
    y = pd.to_numeric(g[score_col], errors="coerce")
    ok = ~(t.isna() | y.isna())
    t, y = t[ok].to_numpy(float), y[ok].to_numpy(float)
    res = {"n_obs": int(len(y))}
    if len(y) == 0:
        return res
    span = t.max() - t.min()
    res["coverage"] = round(min(1.0, len(y) / (span // expected_days + 1)), 3)
    res["max_gap"] = float(np.diff(t).max()) if len(t) > 1 else None
    if len(y) >= 3 and np.ptp(t) > 0:
        res["slope_per_week"] = float(np.polyfit(t / 7, y, 1)[0])
    if len(y) >= 2:
        ch = classify_change("phq9", int(y[0]), int(y[-1]))
        res["first"], res["last"], res["direction"] = int(y[0]), int(y[-1]), ch.direction
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--id", required=True)
    ap.add_argument("--time", required=True)
    ap.add_argument("--score")
    ap.add_argument("--items")
    ap.add_argument("--expected-days", type=int, default=1,
                    help="ожидаемый интервал между анкетами в датасете (для полноты)")
    ap.add_argument("--out", default="analysis/results/monitoring")
    a = ap.parse_args()

    df = pd.read_csv(a.csv)
    if a.items:
        cols = a.items.split(",")
        df["_score"] = [score("phq9", [None if pd.isna(v) else int(v) for v in r]).total
                        for r in df[cols].itertuples(index=False)]
        sc = "_score"
    else:
        sc = a.score
    rows = {pid: per_person(g, a.time, sc, a.expected_days) for pid, g in df.groupby(a.id)}
    summary = pd.DataFrame(rows).T
    agg = {
        "n_people": len(summary),
        "median_obs": float(summary["n_obs"].median()),
        "median_coverage": float(pd.to_numeric(summary.get("coverage"), errors="coerce").median()),
        "direction_counts": summary.get("direction", pd.Series(dtype=str)).value_counts().to_dict(),
        "warning": "Если анкета ежедневная — окна по 14 дней перекрываются; динамика описательная.",
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out.with_suffix(".per_person.csv"))
    out.with_suffix(".json").write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
