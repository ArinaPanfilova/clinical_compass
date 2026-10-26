"""Оценка извлечения ключевых сведений из медицинских документов (kompas_core.extraction).

Приёмочный набор — пул `test` генератора synthetic/documents.py (n=300, фиксированный seed):
перефразировки, которых нет в пуле разработки `dev`. Извлекатель на нём не настраивается.
Для сравнения тем же кодом считается `dev` — разница и есть цена перефразировок.

Что считаем:
* precision / recall / F1 по группам: диагнозы (код + статус), препараты (МНН + статус),
  дозы (МНН + доза; только где доза есть в эталоне или в ответе), аллергии (аллерген);
* статус аллергий: не упомянуты / отрицаются / перечислены;
* каждый факт безопасности по трём значениям True / False / None: матрица ошибок,
  P/R/F1 для каждого значения, macro-F1 по значениям, которые встречаются;
* опасные ошибки — False или None при эталоне True для противопоказаний Авиандра
  (из карточки kompas_core/drugs/aviandr.yaml); False при True — самая опасная, считается отдельно;
  то же для предостережений — отдельной строкой;
* всё это с разбивкой по шаблонам А / Б / В.

Единица — документ; элементы внутри документа сравниваются как множества.

Запуск: python evaluation/evaluate_extraction.py → evaluation/results/extraction_eval.{md,json}
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.evaluate_alerts import pct, wilson   # noqa: E402
from kompas_core.drugs import load_card               # noqa: E402
from synthetic.documents import SAFETY_KEYS, TEMPLATES, generate_documents  # noqa: E402

N_DOCS = 300
TEST_SEED = 2026
DEV_SEED = 42

_CARD = load_card("aviandr")
CONTRAINDICATION_KEYS = tuple(c["fact"].removeprefix("safety.") for c in _CARD["contraindications"])
CAUTION_KEYS = tuple(k for k in (c["fact"].removeprefix("safety.") for c in _CARD["cautions"])
                     if k in SAFETY_KEYS)
GROUPS = ("diagnoses", "medications", "doses", "allergies")
VALUES = (True, False, None)
GROUP_TITLES = {"diagnoses": "Диагнозы (код + статус)", "medications": "Препараты (МНН + статус)",
                "doses": "Дозы (МНН + доза)", "allergies": "Аллергии (аллерген)"}


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Precision, recall, F1. Нечего находить и ничего не найдено — 1.0 по всем трём."""
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def to_truth_shape(out: dict) -> dict:
    """Выход extract() (с цитатами) → форма эталона. Эталонную форму возвращает как есть."""
    def val(v):
        return v["value"] if isinstance(v, dict) else v

    def name(a):
        return a["name"] if isinstance(a, dict) else a

    allergies = out.get("allergies")
    return {
        "diagnoses": [{"code": d["code"], "status": d["status"]} for d in out.get("diagnoses", [])],
        "medications": [{"mnn": m["mnn"], "dose_mg": m.get("dose_mg"), "status": m["status"]}
                        for m in out.get("medications", [])],
        "allergies": None if allergies is None else [name(a) for a in allergies],
        "safety": {k: val(out.get("safety", {}).get(k)) for k in SAFETY_KEYS},
    }


def _items(shape: dict) -> dict[str, set]:
    return {
        "diagnoses": {(d["code"], d["status"]) for d in shape["diagnoses"]},
        "medications": {(m["mnn"], m["status"]) for m in shape["medications"]},
        "doses": {(m["mnn"], float(m["dose_mg"])) for m in shape["medications"] if m["dose_mg"] is not None},
        "allergies": set(shape["allergies"] or ()),
    }


def _allergy_status(a) -> str:
    return "not_mentioned" if a is None else "denied" if not a else "present"


def _group_summary(c: Counter) -> dict:
    p, r, f = prf(c["tp"], c["fp"], c["fn"])
    return {"tp": c["tp"], "fp": c["fp"], "fn": c["fn"], "precision": p, "recall": r, "f1": f}


def _safety_summary(conf: dict) -> dict:
    per_value, f1s = {}, []
    total = sum(sum(row.values()) for row in conf.values())
    correct = sum(conf[str(v)][str(v)] for v in VALUES)
    for v in VALUES:
        s = str(v)
        tp = conf[s][s]
        fp = sum(conf[str(t)][s] for t in VALUES if t is not v)
        fn = sum(conf[s][str(q)] for q in VALUES if q is not v)
        p, r, f = prf(tp, fp, fn)
        per_value[s] = {"support": tp + fn, "predicted": tp + fp, "precision": p, "recall": r, "f1": f}
        if tp + fn or tp + fp:
            f1s.append(f)
    return {"confusion": conf, "per_value": per_value,
            "macro_f1": sum(f1s) / len(f1s) if f1s else 1.0,
            "accuracy": correct / total if total else 1.0}


def _empty_conf() -> dict:
    return {str(t): {str(p): 0 for p in VALUES} for t in VALUES}


def evaluate(docs: list[dict], extract_fn, max_examples: int = 25) -> dict:
    groups = {g: Counter() for g in GROUPS}
    by_t = defaultdict(lambda: {"n_docs": 0, "groups": {g: Counter() for g in GROUPS},
                                "safety": {k: _empty_conf() for k in SAFETY_KEYS},
                                "dangerous": 0, "false_at_true": 0})
    conf = {k: _empty_conf() for k in SAFETY_KEYS}
    al_conf = Counter()
    dang = {k: {"false_at_true": 0, "none_at_true": 0} for k in CONTRAINDICATION_KEYS}
    caut = {k: {"false_at_true": 0, "none_at_true": 0} for k in CAUTION_KEYS}
    positives = Counter()
    examples, errors = [], defaultdict(Counter)
    times = []

    for doc in docs:
        t0 = time.perf_counter()
        raw = extract_fn(doc["text"])
        times.append((time.perf_counter() - t0) * 1000)
        pred, truth = to_truth_shape(raw), doc["truth"]
        T = by_t[doc["template"]]
        T["n_docs"] += 1
        ti, pi = _items(truth), _items(pred)
        for g in GROUPS:
            tp, fp, fn = len(ti[g] & pi[g]), len(pi[g] - ti[g]), len(ti[g] - pi[g])
            for c in (groups[g], T["groups"][g]):
                c["tp"] += tp
                c["fp"] += fp
                c["fn"] += fn
            for x in pi[g] - ti[g]:
                errors[g][f"лишнее {x}"] += 1
            for x in ti[g] - pi[g]:
                errors[g][f"пропуск {x}"] += 1
        al_conf[(_allergy_status(truth["allergies"]), _allergy_status(pred["allergies"]))] += 1
        for k in SAFETY_KEYS:
            tv, pv = truth["safety"][k], pred["safety"][k]
            conf[k][str(tv)][str(pv)] += 1
            T["safety"][k][str(tv)][str(pv)] += 1
            if tv != pv:
                errors[k][f"эталон {tv} → {pv}"] += 1
            if tv is True:
                positives[k] += 1
                if pv is not True:
                    kind = "false_at_true" if pv is False else "none_at_true"
                    if k in dang:
                        dang[k][kind] += 1
                        T["dangerous"] += 1
                        T["false_at_true"] += pv is False
                        if len(examples) < max_examples:
                            ev = (raw.get("safety", {}).get(k) or {}).get("evidence") if isinstance(
                                raw.get("safety", {}).get(k), dict) else None
                            examples.append({"doc_id": doc["doc_id"], "template": doc["template"], "key": k,
                                             "predicted": pv, "evidence": ev["quote"] if ev else None})
                    elif k in caut:
                        caut[k][kind] += 1

    al_total = sum(al_conf.values())
    fat = sum(v["false_at_true"] for v in dang.values())
    nat = sum(v["none_at_true"] for v in dang.values())
    n_pos = sum(positives[k] for k in CONTRAINDICATION_KEYS)
    res = {
        "n_docs": len(docs),
        "groups": {g: _group_summary(c) for g, c in groups.items()},
        "safety": {k: _safety_summary(conf[k]) for k in SAFETY_KEYS},
        "allergy_status": {"accuracy": sum(v for (t, p), v in al_conf.items() if t == p) / al_total if al_total else 1.0,
                           "confusion": {f"{t} → {p}": v for (t, p), v in sorted(al_conf.items())}},
        "dangerous": {"total": fat + nat, "false_at_true": fat, "none_at_true": nat, "by_key": dang,
                      "contraindication_positives": n_pos,
                      "positives_by_key": {k: positives[k] for k in CONTRAINDICATION_KEYS},
                      "rule_of_three_upper": (3 / n_pos) if (fat + nat == 0 and n_pos) else None,
                      "miss_rate_ci": wilson(fat + nat, n_pos) if n_pos else None,
                      "examples": examples},
        "cautions_missed": caut,
        "by_template": {
            t: {"n_docs": v["n_docs"], "groups": {g: _group_summary(c) for g, c in v["groups"].items()},
                "safety_macro_f1": {k: _safety_summary(v["safety"][k])["macro_f1"] for k in SAFETY_KEYS},
                "dangerous": v["dangerous"], "false_at_true": v["false_at_true"]}
            for t, v in sorted(by_t.items())},
        "top_errors": {k: c.most_common(8) for k, c in errors.items()},
        "latency_ms": {"p50": pct(times, .5), "p95": pct(times, .95)} if times else None,
    }
    return res


# --- Отчёт -----------------------------------------------------------------------------------

def _f(x: float) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"


def to_markdown(test: dict, dev: dict, meta: dict) -> str:
    L = [f"# Извлечение ключевых сведений из медицинских документов",
         "",
         f"Приёмочный набор: пул `test`, n={test['n_docs']}, seed={meta['test_seed']} — перефразировки, "
         "которых нет в пуле разработки. Для сравнения: пул `dev`, "
         f"n={dev['n_docs']}, seed={meta['dev_seed']} (на нём извлекатель разрабатывался).",
         "",
         "> Синтетические документы: проверка реализации на заданной модели вариативности текста, "
         "**не** оценка на реальных выписках. Пул `test` написан отдельным исполнителем до извлекателя; "
         "извлекатель по ошибкам на `test` не настраивался.",
         ""]

    L += ["## Группы сущностей", "",
          "| Группа | test P | test R | test F1 | TP/FP/FN (test) | dev F1 |",
          "|---|---|---|---|---|---|"]
    for g in GROUPS:
        t, d = test["groups"][g], dev["groups"][g]
        L.append(f"| {GROUP_TITLES[g]} | {_f(t['precision'])} | {_f(t['recall'])} | **{_f(t['f1'])}** | "
                 f"{t['tp']}/{t['fp']}/{t['fn']} | {_f(d['f1'])} |")
    L.append(f"| Статус аллергий (нет сведений / отрицает / есть), точность | | | "
             f"**{_f(test['allergy_status']['accuracy'])}** | | {_f(dev['allergy_status']['accuracy'])} |")
    L.append("")

    L += ["## Факты безопасности (три значения: True / False / None)", "",
          "| Факт | test macro-F1 | F1 True | F1 False | F1 None | точность | dev macro-F1 |",
          "|---|---|---|---|---|---|---|"]
    for k in SAFETY_KEYS:
        s, d = test["safety"][k], dev["safety"][k]
        pv = s["per_value"]
        mark = " (противопоказание)" if k in CONTRAINDICATION_KEYS else ""
        L.append(f"| `{k}`{mark} | **{_f(s['macro_f1'])}** | {_f(pv['True']['f1'])} | {_f(pv['False']['f1'])} | "
                 f"{_f(pv['None']['f1'])} | {_f(s['accuracy'])} | {_f(d['macro_f1'])} |")
    L.append("")

    for title, r in (("test", test), ("dev", dev)):
        dg = r["dangerous"]
        L += [f"## Опасные ошибки по противопоказаниям Авиандра — {title}", "",
              f"Эталон True, извлечено False или None: **{dg['total']}** из {dg['contraindication_positives']} "
              f"положительных (False при True — **{dg['false_at_true']}**, None при True — {dg['none_at_true']})."]
        if dg["rule_of_three_upper"] is not None:
            L.append(f"0 ошибок; верхняя граница доли пропусков по правилу трёх ≈ {dg['rule_of_three_upper']:.3f}.")
        elif dg["miss_rate_ci"]:
            p, lo, hi = dg["miss_rate_ci"]
            L.append(f"Доля пропусков {p:.3f}, 95% ДИ Уилсона [{lo:.3f}; {hi:.3f}].")
        L += ["", "| Противопоказание | положительных | False при True | None при True |", "|---|---|---|---|"]
        for k in CONTRAINDICATION_KEYS:
            v = dg["by_key"][k]
            L.append(f"| `{k}` | {dg['positives_by_key'][k]} | {v['false_at_true']} | {v['none_at_true']} |")
        cm = r["cautions_missed"]
        L += ["", "Предостережения (не противопоказания), пропуски при эталоне True: " +
              ", ".join(f"`{k}` — False {v['false_at_true']}, None {v['none_at_true']}" for k, v in cm.items()), ""]
        if dg["examples"]:
            L += ["Примеры:", ""]
            L += [f"- {e['doc_id']} [{e['template']}] `{e['key']}` → {e['predicted']}"
                  + (f", цитата: «{e['evidence']}»" if e["evidence"] else "") for e in dg["examples"][:10]]
            L.append("")

    L += ["## По шаблонам (test)", "",
          "А — выписка с разделами, Б — осмотр сплошным текстом, В — краткое направление с сокращениями.", "",
          "| Шаблон | документов | F1 диагнозы | F1 препараты | F1 дозы | F1 аллергии | мин. macro-F1 по фактам | опасных ошибок (из них False) |",
          "|---|---|---|---|---|---|---|---|"]
    for t in TEMPLATES:
        if t not in test["by_template"]:
            continue
        v = test["by_template"][t]
        g = v["groups"]
        worst = min(v["safety_macro_f1"].items(), key=lambda kv: kv[1])
        L.append(f"| {t} | {v['n_docs']} | {_f(g['diagnoses']['f1'])} | {_f(g['medications']['f1'])} | "
                 f"{_f(g['doses']['f1'])} | {_f(g['allergies']['f1'])} | {_f(worst[1])} (`{worst[0]}`) | "
                 f"{v['dangerous']} ({v['false_at_true']}) |")
    L.append("")

    L += ["## Частые ошибки на test", ""]
    if test["top_errors"]:
        for k, lst in sorted(test["top_errors"].items()):
            L.append(f"- `{k}`: " + "; ".join(f"{e} ×{n}" for e, n in lst[:5]))
    else:
        L.append("- нет")
    L.append("")

    worse = [g for g in GROUPS if test["groups"][g]["f1"] < dev["groups"][g]["f1"] - 1e-9]
    worse += [k for k in SAFETY_KEYS if test["safety"][k]["macro_f1"] < dev["safety"][k]["macro_f1"] - 1e-9]
    L += ["## test против dev", ""]
    if worse:
        L.append("На `test` хуже, чем на `dev`: " + ", ".join(f"`{w}`" for w in worse) +
                 ". Это цена перефразировок, которых не было при разработке; извлекатель под них не подгонялся.")
    else:
        L.append("На `test` не хуже, чем на `dev`, ни по одной группе.")
    lat = test["latency_ms"]
    L += ["", f"Время извлечения на документ: p50 = {lat['p50']:.2f} мс, p95 = {lat['p95']:.2f} мс.", ""]
    return "\n".join(L)


def run(n: int = N_DOCS, test_seed: int = TEST_SEED, dev_seed: int = DEV_SEED) -> tuple[dict, dict]:
    from kompas_core.extraction import extract
    test = evaluate(generate_documents(n, test_seed, "test"), extract)
    dev = evaluate(generate_documents(n, dev_seed, "dev"), extract)
    return test, dev


if __name__ == "__main__":
    test_res, dev_res = run()
    meta = {"n": N_DOCS, "test_seed": TEST_SEED, "dev_seed": DEV_SEED}
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "extraction_eval.json").write_text(
        json.dumps({"meta": meta, "test": test_res, "dev": dev_res}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    md = to_markdown(test_res, dev_res, meta)
    (out_dir / "extraction_eval.md").write_text(md, encoding="utf-8")
    print(md)
