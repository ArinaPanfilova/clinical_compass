"""Оценка алертинга и маршрутизации на синтетической когорте.

Что считаем:
* чувствительность, специфичность, PPV с 95% ДИ Уилсона;
* если FN = 0 — дополнительно «правило трёх» (верхняя граница доли пропусков ≈ 3/n);
* разбивку пропусков по механизму (архетипу) — средняя метрика не должна прятать
  редкие опасные ошибки;
* время работы ядра (p50/p95/p99) на одного пациента.

Единица анализа — пациент (одна оценка на пациента), поэтому зависимость повторных
измерений здесь не возникает. PPV зависит от доли положительных в когорте, которую
задаёт генератор, поэтому на реальную практику не переносится.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kompas_core import evaluate_patient          # noqa: E402
from synthetic.generator import generate          # noqa: E402

SAFETY_RULES = {"SAFE-001", "SAFE-002", "SAFE-003", "SAFE-004", "SAFE-005"}


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (p, max(0.0, c - h), min(1.0, c + h))


def confusion(pairs):
    c = Counter()
    for truth, pred in pairs:
        c[("T" if pred == truth else "F") + ("P" if pred else "N")] += 1
    tp, fp, tn, fn = c["TP"], c["FP"], c["TN"], c["FN"]
    res = {"TP": tp, "FP": fp, "TN": tn, "FN": fn,
           "sensitivity": wilson(tp, tp + fn), "specificity": wilson(tn, tn + fp),
           "ppv": wilson(tp, tp + fp)}
    if fn == 0 and tp > 0:
        res["rule_of_three_upper_miss_rate"] = 3 / tp
    return res


def pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return xs[f] if f == c else xs[f] + (xs[c] - xs[f]) * (k - f)


def run(n=1000, seed=42):
    cohort = generate(n, seed)
    safety, referral, ae, times = [], [], [], []
    misses = defaultdict(list)
    for rec, truth in cohort:
        out = evaluate_patient(rec, drugs=["aviandr"])
        times.append(out["elapsed_ms"])
        ids = {f["rule_id"] for f in out["findings"]}
        pred_s = bool(ids & SAFETY_RULES)
        pred_r = any(f["routing"] == "mandatory" for f in out["findings"])
        pred_ae = any(f["kind"] == "therapy_warning" for f in out["findings"])
        safety.append((truth.safety_signal, pred_s))
        referral.append((truth.mandatory_referral, pred_r))
        ae.append((truth.ae_present, pred_ae))
        if truth.safety_signal and not pred_s:
            misses["safety_FN"].append((truth.archetype, rec["diary"][-1]["text"] if rec["diary"] else None))
        if truth.mandatory_referral and not pred_r:
            misses["referral_FN"].append(truth.archetype)
        if pred_s and not truth.safety_signal:
            misses["safety_FP"].append(truth.archetype)
            misses["safety_FP_rule"] += sorted(ids & SAFETY_RULES)
    return {
        "n_patients": n, "seed": seed,
        "safety_signal": confusion(safety),
        "mandatory_referral": confusion(referral),
        "adverse_events": confusion(ae),
        "latency_ms": {"p50": pct(times, .5), "p95": pct(times, .95), "p99": pct(times, .99)},
        "safety_FN_by_mechanism": Counter(a for a, _ in misses["safety_FN"]),
        "safety_FN_texts": Counter(t for _, t in misses["safety_FN"]),
        "safety_FP_by_archetype": Counter(misses["safety_FP"]),
        "safety_FP_by_rule": Counter(misses["safety_FP_rule"]),
        "referral_FN_by_archetype": Counter(misses["referral_FN"]),
        "archetypes": Counter(t.archetype for _, t in cohort),
    }


def fmt_ci(t):
    p, lo, hi = t
    return f"{p:.3f} [{lo:.3f}; {hi:.3f}]"


def to_markdown(r: dict) -> str:
    L = [f"# Оценка алертинга на синтетической когорте (n={r['n_patients']}, seed={r['seed']})", "",
         "> Верификация реализации протокола при заданной модели шума, **не** клиническая валидация.",
         "> PPV зависит от доли положительных, заданной генератором.", ""]
    for key, title in (("safety_signal", "Сигнал безопасности"),
                       ("mandatory_referral", "Направление «обязательно»"),
                       ("adverse_events", "Нежелательные явления")):
        c = r[key]
        L += [f"## {title}", "",
              f"TP={c['TP']} FP={c['FP']} TN={c['TN']} FN={c['FN']}", "",
              f"- Чувствительность: {fmt_ci(c['sensitivity'])}",
              f"- Специфичность: {fmt_ci(c['specificity'])}",
              f"- PPV: {fmt_ci(c['ppv'])}"]
        if "rule_of_three_upper_miss_rate" in c:
            L.append(f"- 0 пропусков; верхняя граница доли пропусков по правилу трёх ≈ {c['rule_of_three_upper_miss_rate']:.3f}")
        L.append("")
    L += ["## Пропуски сигнала безопасности по механизму", ""]
    L += [f"- {k}: {v}" for k, v in r["safety_FN_by_mechanism"].items()] or ["- нет"]
    L += ["", "Тексты, которые словарь пропустил:", ""]
    L += [f"- «{k}»: {v}" for k, v in r["safety_FN_texts"].items() if k] or ["- нет"]
    L += ["", "Ложные срабатывания по правилу (п.9 = 1 без латентных мыслей; пропуск п.9):", ""]
    L += [f"- {k}: {v}" for k, v in r["safety_FP_by_rule"].items()] or ["- нет"]
    L += ["", "## Пропуски направления «обязательно» по архетипу", ""]
    L += [f"- {k}: {v}" for k, v in r["referral_FN_by_archetype"].items()] or ["- нет"]
    lat = r["latency_ms"]
    L += ["", "## Время работы ядра на пациента", "",
          f"p50 = {lat['p50']:.2f} мс, p95 = {lat['p95']:.2f} мс, p99 = {lat['p99']:.2f} мс "
          "(только вычисление правил, без сети и БД)"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    res = run()
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "alert_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    md = to_markdown(res)
    (out_dir / "alert_eval.md").write_text(md, encoding="utf-8")
    print(md)
