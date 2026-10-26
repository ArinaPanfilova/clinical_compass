"""Проверка расчёта PHQ-9 и сигналов по п.9 на реальных ответах (открытый датасет, CC0).

Датасет: «14-day AA depression symptoms, mood and PHQ-9» (Kaggle, thedevastator/phq-9-depression-assessment):
185 человек, у каждого одна анкета PHQ-9 по пунктам и 14 дней оценок настроения (EMA, 3 раза в день).
Выборка не клиническая, поэтому это проверка реализации на настоящих паттернах ответов
(пропуски, крайние значения, п.9 при низкой сумме), а не клиническая валидация.

    python evaluation/real_phq9_kaggle.py     # → evaluation/results/real_phq9.md
"""
from __future__ import annotations

import csv
import io
import statistics
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kompas_core import evaluate_patient          # noqa: E402
from kompas_core.scales import score              # noqa: E402

URL = "https://www.kaggle.com/api/v1/datasets/download/thedevastator/phq-9-depression-assessment"
CSV = ROOT / "data" / "kaggle_phq9" / "Dataset_14-day_AA_depression_symptoms_mood_and_PHQ-9.csv"
OUT = ROOT / "evaluation" / "results" / "real_phq9.md"
ITEMS = [f"phq{i}" for i in range(1, 10)]


def load() -> list[dict]:
    if not CSV.exists():
        CSV.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=60) as r:
            zipfile.ZipFile(io.BytesIO(r.read())).extractall(CSV.parent)
    return list(csv.DictReader(CSV.open(encoding="utf-8")))


def num(v: str):
    return None if v in ("", "NA") else int(float(v))


def cronbach(rows: list[list[int]]) -> float:
    k = len(rows[0])
    item_var = sum(statistics.pvariance([r[i] for r in rows]) for i in range(k))
    total_var = statistics.pvariance([sum(r) for r in rows])
    return k / (k - 1) * (1 - item_var / total_var)


def ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for t in range(i, j + 1):
            r[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return cov / (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5


def main() -> None:
    rows = load()
    users: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        users[r["user_id"]].append(r)

    cats, item9, alerts, flags = Counter(), Counter(), Counter(), Counter()
    complete, low_sum_item9, mood_pairs, ms = [], 0, [], []
    for uid, rs in users.items():
        answers = [num(rs[0][k]) for k in ITEMS]
        s = score("phq9", answers)
        cats[s.category_label or "не рассчитана"] += 1
        item9[s.safety_item_value if s.safety_item_value is not None else "пропущен"] += 1
        flags.update(s.flags)
        if None not in answers:
            complete.append(answers)
        record = {"patient_id": uid, "assessments": [{"date": rs[0]["time"][:10], "scale": "phq9", "answers": answers}]}
        ev = evaluate_patient(record)
        ms.append(ev["elapsed_ms"])
        fired = {f["rule_id"] for f in ev["findings"] if f["kind"] == "alert"}
        alerts.update(fired)
        if (s.safety_item_value or 0) >= 1 and s.total is not None and s.total < 10:
            low_sum_item9 += 1
        mood = [num(r["happiness.score"]) for r in rs if num(r["happiness.score"]) is not None]
        if mood and s.total is not None:
            mood_pairs.append((s.total, statistics.fmean(mood)))

    n = len(users)
    any9 = sum(v for k, v in item9.items() if isinstance(k, int) and k >= 1)
    rho = spearman([a for a, _ in mood_pairs], [b for _, b in mood_pairs])
    lines = [
        "# PHQ-9 на реальных ответах: открытый датасет Kaggle (CC0)",
        "",
        "Датасет «14-day AA depression symptoms, mood and PHQ-9»: "
        f"{n} человек, {len(rows)} записей настроения за 14 дней, по одной анкете PHQ-9 на человека.",
        "",
        "> Выборка не клиническая. Это проверка расчёта шкалы и правил на настоящих паттернах ответов, "
        "а не клиническая валидация сигналов.",
        "",
        "## Расчёт шкалы",
        "",
        f"- Анкет полностью без пропусков: {len(complete)} из {n}; с досчётом по правилу паспорта шкалы: "
        f"{flags['prorated']}; слишком много пропусков, сумма не считается: {flags['too_many_missing']}.",
        f"- Внутренняя согласованность (α Кронбаха, полные анкеты): {cronbach(complete):.2f} "
        "(русская версия у Золотаревой, 2023: 0,89).",
        f"- Связь суммы PHQ-9 со средним настроением за 14 дней (ρ Спирмена, n = {len(mood_pairs)}): {rho:.2f}.",
        "",
        "| Категория тяжести | n |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])],
        "",
        "## Пункт 9 и сигналы",
        "",
        f"- Ответ на п.9 не «совсем нет»: {any9} из {n} ({any9 / n:.0%}); пропущен: {item9['пропущен']}.",
        f"- Из них при сумме PHQ-9 < 10, то есть порог по сумме сигнала бы не дал: **{low_sum_item9}**. "
        "Поэтому сигнал по п.9 в Компасе не зависит от суммы.",
        *[f"- {rule}: {cnt} сигналов" for rule, cnt in sorted(alerts.items())],
        f"- Время правил на анкету: p50 = {statistics.median(ms):.2f} мс.",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
