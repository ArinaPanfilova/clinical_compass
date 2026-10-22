"""Анализ открытых датасетов с PHQ-9/GAD-7 (Mendeley, Kaggle).

Запуск (локально или в Colab, сюда сеть не пускает):
    python analysis/psychometrics.py data/mendeley.csv --out analysis/results/mendeley
    python analysis/psychometrics.py data/file.csv --phq "q1,q2,...,q9" --gad "g1,...,g7"

Что считает:
1. Описание: n, доля пропусков по пунктам, распределение по категориям тяжести.
2. Надёжность: α Кронбаха с бутстреп-ДИ, корреляция «пункт — остаток шкалы».
3. Нагрузка алертами: доля п.9 ≥ 1 и ≥ 2 → ожидаемое число алертов на 100 анкет.
4. Порог надёжного изменения (RCI) по SD и α выборки.
5. Короткие формы PHQ-2/GAD-2 → PHQ-9/GAD-7 ≥ 10: ROC-AUC, чувствительность/специфичность.
   Внимание: PHQ-2 входит в PHQ-9, поэтому AUC завышен (part-whole overlap).
   Это проверка согласованности короткой формы, а не диагностическая точность.

Ограничение для слайдов: если выборка студенческая, а не клиническая, все результаты
описывают эту популяцию и не переносятся на пациентов первичного звена.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kompas_core import score, reliable_change_threshold  # noqa: E402


def detect_items(df: pd.DataFrame, prefix_regex: str, n: int) -> list[str] | None:
    """Ищет колонки вида PHQ9_1 … PHQ9_9 / phq_q1 … (по номеру в конце имени)."""
    cand = {}
    for c in df.columns:
        if re.search(prefix_regex, str(c), re.I):
            m = re.search(r"(\d+)\D*$", str(c))
            if m and 1 <= int(m.group(1)) <= n:
                cand.setdefault(int(m.group(1)), c)
    return [cand[i] for i in range(1, n + 1)] if len(cand) == n else None


def cronbach_alpha(items: np.ndarray) -> float:
    items = items[~np.isnan(items).any(axis=1)]
    k = items.shape[1]
    var_items = items.var(axis=0, ddof=1).sum()
    var_total = items.sum(axis=1).var(ddof=1)
    return k / (k - 1) * (1 - var_items / var_total)


def bootstrap_ci(f, data: np.ndarray, B: int = 1000, seed: int = 0):
    rnd = np.random.default_rng(seed)
    n = len(data)
    vals = [f(data[rnd.integers(0, n, n)]) for _ in range(B)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def item_rest_corr(items: np.ndarray) -> list[float]:
    items = items[~np.isnan(items).any(axis=1)]
    tot = items.sum(axis=1)
    res = []
    with np.errstate(invalid="ignore", divide="ignore"):
        for j in range(items.shape[1]):
            r = np.corrcoef(items[:, j], tot - items[:, j])[0, 1]
            res.append(None if np.isnan(r) else float(r))   # None: пункт без разброса
    return res


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """AUC через статистику Манна–Уитни (с учётом связей)."""
    from scipy.stats import rankdata
    r = rankdata(scores)
    n1, n0 = labels.sum(), (~labels).sum()
    return float((r[labels].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [float(p), float(c - h), float(c + h)]


def analyze_scale(df: pd.DataFrame, cols: list[str], sid: str) -> dict:
    X = df[cols].apply(pd.to_numeric, errors="coerce")
    out: dict = {"columns": cols, "n_rows": int(len(X)),
                 "missing_by_item": X.isna().mean().round(4).tolist()}
    bad = ((X < 0) | (X > 3)).sum().sum()
    out["out_of_range_values"] = int(bad)

    scored = [score(sid, [None if pd.isna(v) else int(v) for v in row])
              for row in X.where((X >= 0) & (X <= 3)).itertuples(index=False)]
    totals = np.array([s.total for s in scored if s.total is not None], dtype=float)
    out["n_scored"] = int(len(totals))
    out["n_prorated"] = int(sum(s.prorated for s in scored))
    cats = pd.Series([s.category for s in scored if s.category]).value_counts()
    out["category_counts"] = cats.to_dict()
    out["category_share_ci"] = {k: wilson(int(v), len(totals)) for k, v in cats.items()}
    out["total_mean_sd"] = [float(totals.mean()), float(totals.std(ddof=1))]

    arr = X.to_numpy(dtype=float)
    a = cronbach_alpha(arr)
    complete = arr[~np.isnan(arr).any(axis=1)]
    out["cronbach_alpha"] = float(a)
    out["cronbach_alpha_ci95_bootstrap"] = bootstrap_ci(cronbach_alpha, complete)
    out["item_rest_correlation"] = item_rest_corr(arr)
    thr = reliable_change_threshold(totals.std(ddof=1), a)
    out["reliable_change_threshold_points"] = float(thr)
    out["rci_note"] = ("RCI по α (внутренняя согласованность). Для изменения во времени корректнее "
                       "ретестовая надёжность — если в данных есть повторы, пересчитать по ней.")

    if sid == "phq9":
        item9 = X[cols[8]].dropna()
        n9 = len(item9)
        out["item9_ge1"] = wilson(int((item9 >= 1).sum()), n9)
        out["item9_ge2"] = wilson(int((item9 >= 2).sum()), n9)
        out["expected_safety_alerts_per_100_questionnaires"] = round(100 * out["item9_ge1"][0], 1)

    short = complete[:, :2].sum(axis=1)
    full = complete.sum(axis=1)
    lab = full >= 10
    if lab.any() and (~lab).any():
        out["short2_vs_full_ge10"] = {
            "auc": auc(short, lab),
            "at_short_ge3": {"sensitivity": wilson(int(((short >= 3) & lab).sum()), int(lab.sum())),
                             "specificity": wilson(int(((short < 3) & ~lab).sum()), int((~lab).sum()))},
            "note": "Короткая форма входит в полную → AUC завышен; это согласованность, не точность диагноза",
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--phq", help="9 колонок через запятую")
    ap.add_argument("--gad", help="7 колонок через запятую")
    ap.add_argument("--out", default="analysis/results/dataset")
    a = ap.parse_args()

    df = pd.read_csv(a.csv) if not a.csv.endswith((".xlsx", ".xls")) else pd.read_excel(a.csv)
    print(f"Строк: {len(df)}; колонки: {list(df.columns)[:40]}")
    phq = a.phq.split(",") if a.phq else detect_items(df, r"phq", 9)
    gad = a.gad.split(",") if a.gad else detect_items(df, r"gad", 7)
    res = {"source_file": a.csv, "n_rows": len(df)}
    if phq:
        res["phq9"] = analyze_scale(df, phq, "phq9")
    else:
        print("Колонки PHQ-9 не найдены — укажите --phq")
    if gad:
        res["gad7"] = analyze_scale(df, gad, "gad7")
    else:
        print("Колонки GAD-7 не найдены — укажите --gad")
    if phq and gad:
        t = pd.DataFrame({"p": df[phq].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=9),
                          "g": df[gad].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=7)}).dropna()
        res["phq9_gad7_spearman"] = float(t.corr(method="spearman").iloc[0, 1])
        res["comorbid_both_ge10_share"] = wilson(int(((t.p >= 10) & (t.g >= 10)).sum()), len(t))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()
