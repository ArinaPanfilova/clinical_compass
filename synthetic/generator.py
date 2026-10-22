"""Генератор синтетических пациентов с НЕЗАВИСИМОЙ эталонной разметкой.

Методологический принцип: эталон берётся из латентного «истинного» состояния, которое
задаёт генератор (есть ли мысли о самоповреждении, тяжесть, нежелательное явление),
а НЕ из применения тех же правил к тем же данным. Иначе метрика была бы тавтологией.

Наблюдаемые данные получаются из латентного состояния через шум измерения:
* ответы на пункты шкал — случайные вокруг латентной тяжести;
* часть пациентов с мыслями о самоповреждении отвечает на п.9 «0» и пишет об этом только
  в дневнике, причём частью — перефразировками вне словаря;
* случайные пропуски пунктов и анкет.

Ограничение: это верификация (код реализует протокол при заданной модели шума),
а не клиническая валидация. Для валидации нужны случаи, размеченные двумя экспертами.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# Тексты дневника. Часть позитивных фраз специально НЕ покрыта словарём text_screen.
POS_IN_DICT = ["Иногда думаю, что не хочу жить", "Хочется умереть, всё бессмысленно",
               "Думаю о том, чтобы причинить себе вред", "Не вижу выхода из ситуации",
               "Нет смысла жить дальше"]
POS_PARAPHRASE = ["Всем было бы легче без меня", "Устала жить так",
                  "Хочу заснуть и не проснуться", "Хочется просто исчезнуть"]
NEGATED = ["Мыслей о суициде нет", "Никогда не думала причинить себе вред",
           "Не было мыслей о том, что не хочу жить"]
NEUTRAL = ["Сегодня гуляла, стало немного легче", "Плохо спал, устал на работе",
           "Тревожно перед встречей, но справилась", "Обычный день", "Принял таблетку вовремя",
           "Сложно сосредоточиться"]

ARCHETYPES = {
    # имя: вес
    "stable_mild": 18, "improving": 18, "worsening": 10, "ideation_item9": 10,
    "ideation_text_only": 6, "negated_text": 6, "emergency": 3, "serious_ae": 4,
    "nonserious_ae": 8, "missing_reports": 8, "mania": 3, "minor": 2, "severe_stable": 4,
}


@dataclass
class Truth:
    safety_signal: bool        # нужна оценка безопасности врачом
    mandatory_referral: bool   # нужно направление (латентная тяжесть/мания/возраст/ideation≥2)
    ae_present: bool
    archetype: str


def expected_item(mu: float, sd: float = 0.7) -> float:
    """Матожидание наблюдаемого ответа clip(round(N(mu, sd)), 0, 3) — с учётом усечения.

    Нужно, чтобы эталон тяжести совпадал с тем, что шкала в среднем может показать,
    а не с латентным значением, которое усечение систематически занижает у краёв.
    """
    Phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    # P(ответ ≥ k) = P(N ≥ k − 0.5) для k = 1, 2, 3
    return sum(1 - Phi((k - 0.5 - mu) / sd) for k in (1, 2, 3))


def _items(rnd: random.Random, n: int, latent_mean_item: float, p_missing: float = 0.0):
    out = []
    for _ in range(n):
        if rnd.random() < p_missing:
            out.append(None)
            continue
        v = round(rnd.gauss(latent_mean_item, 0.7))
        out.append(max(0, min(3, v)))
    return out


def make_patient(pid: str, archetype: str, rnd: random.Random, start: date) -> tuple[dict, Truth]:
    visits = rnd.randint(3, 6)
    sev0 = {"stable_mild": 0.7, "improving": 1.8, "worsening": 1.2, "ideation_item9": 1.9,
            "ideation_text_only": 1.6, "negated_text": 1.1, "emergency": 2.2,
            "serious_ae": 1.6, "nonserious_ae": 1.5, "missing_reports": 1.4, "mania": 1.2,
            "minor": 1.6, "severe_stable": 2.5}[archetype]
    slope = {"improving": -0.3, "worsening": +0.3}.get(archetype, 0.0)

    assessments, latent_last, ideation_last = [], sev0, 0
    for v in range(visits):
        d = start + timedelta(days=14 * v)
        latent = max(0.0, min(3.0, sev0 + slope * v + rnd.gauss(0, 0.1)))
        latent_last = latent
        p_miss = 0.04
        phq = _items(rnd, 9, latent, p_miss)
        # Латентные мысли о самоповреждении на последнем визите
        ideation = 0
        if v == visits - 1:
            if archetype in ("ideation_item9", "emergency"):
                ideation = rnd.choice([1, 2, 3])
            elif archetype == "ideation_text_only":
                ideation = 1
        if v == visits - 1:
            ideation_last = ideation
            # Пациент с мыслями отвечает на п.9 честно, кроме архетипа «только в тексте»
            if phq[8] is not None:
                phq[8] = 0 if archetype == "ideation_text_only" else ideation
                # Шум: ~3% без латентных мыслей отмечают п.9 = 1 (неоднозначность формулировки,
                # мысли о смерти без намерения). Эталон для них — «нет», так модель создаёт FP.
                if ideation == 0 and archetype != "ideation_text_only" and rnd.random() < 0.03:
                    phq[8] = 1
        elif phq[8] is not None:
            phq[8] = 0
        gad = _items(rnd, 7, max(0.0, latent - 0.2), p_miss)
        if archetype == "missing_reports" and v >= visits - 2:
            continue                         # две последние анкеты не пришли
        assessments.append({"date": d.isoformat(), "scale": "phq9", "answers": phq})
        assessments.append({"date": d.isoformat(), "scale": "gad7", "answers": gad})

    last_day = start + timedelta(days=14 * (visits - 1))
    diary = [{"date": (last_day - timedelta(days=i)).isoformat(), "text": rnd.choice(NEUTRAL)}
             for i in range(rnd.randint(0, 3))]
    if archetype == "ideation_text_only":
        pool = POS_IN_DICT + POS_PARAPHRASE
        diary.append({"date": last_day.isoformat(), "text": rnd.choice(pool)})
    elif archetype == "ideation_item9" and rnd.random() < 0.5:
        diary.append({"date": last_day.isoformat(), "text": rnd.choice(POS_IN_DICT + POS_PARAPHRASE)})
    elif archetype == "negated_text":
        diary.append({"date": last_day.isoformat(), "text": rnd.choice(NEGATED)})

    aes = []
    if archetype == "serious_ae":
        aes.append({"date": last_day.isoformat(), "description": "выраженная аллергическая реакция",
                    "serious": True, "new": True})
    elif archetype == "nonserious_ae":
        aes.append({"date": last_day.isoformat(), "description": rnd.choice(["тошнота", "сонливость", "головная боль"]),
                    "serious": False, "new": True})

    age = rnd.randint(14, 17) if archetype == "minor" else rnd.randint(18, 75)
    record = {
        "patient_id": pid, "age": age, "primary_scale": "phq9",
        "diagnoses": [{"code": rnd.choice(["F41.1", "F32.1", "F32.0"]), "status": rnd.choice(["confirmed", "suspected"])}],
        "assessments": assessments, "expected_interval_days": 14,
        "selfreports_missed_consecutive": 2 if archetype == "missing_reports" else 0,
        "diary": diary, "adverse_events": aes,
        "emergency_button": archetype == "emergency",
        "symptom_checklist": {"mania_or_psychosis": archetype == "mania"},
        "therapy": {"current": [], "weeks_on_current": rnd.choice([2, 4, 8])},
        "safety_profile": {},
    }
    truth = Truth(
        safety_signal=ideation_last > 0 or archetype == "emergency",
        # Ожидаемая сумма PHQ-9 = 8 пунктов по латентной тяжести + п.9 по латентным мыслям
        mandatory_referral=(8 * expected_item(latent_last) + ideation_last >= 20) or ideation_last >= 2
                           or archetype in ("mania", "minor", "emergency"),
        ae_present=bool(aes),
        archetype=archetype,
    )
    return record, truth


def generate(n: int = 1000, seed: int = 42) -> list[tuple[dict, Truth]]:
    rnd = random.Random(seed)
    names, weights = zip(*ARCHETYPES.items())
    out = []
    for i in range(n):
        arch = rnd.choices(names, weights)[0]
        start = date(2026, 6, 1) + timedelta(days=rnd.randint(0, 60))
        out.append(make_patient(f"SYN-{i:04d}", arch, rnd, start))
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="synthetic/cohort.jsonl")
    a = ap.parse_args()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for rec, t in generate(a.n, a.seed):
            f.write(json.dumps({"record": rec, "truth": t.__dict__}, ensure_ascii=False) + "\n")
    print(f"Сохранено {a.n} пациентов в {a.out}")
