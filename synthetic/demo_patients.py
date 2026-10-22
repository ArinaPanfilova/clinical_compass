"""Демонстрационные пациенты под клинические сценарии проектного документа (раздел 14).

Все профили синтетические. Финальные ответы по сценариям утверждают специалисты.
Запуск: python synthetic/demo_patients.py  → frontend/public/mock/patients.json
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kompas_core import evaluate_patient  # noqa: E402

TODAY = date.today()   # даты демо всегда «свежие» относительно дня запуска


def ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()

SAFE = dict(hypersensitivity_aviandr=False, epilepsy_or_organic_brain_lesion=False,
            maoi_within_2_weeks=False, renal_gfr_below_60=False, hepatic_insufficiency=False,
            pregnancy=False, breastfeeding=False, cardiovascular_disease=False,
            endocrine_disorder=False, substance_dependence=False, lactose_intolerance=False,
            drives_vehicles=False)


def series(totals_phq, totals_gad, item9_last=0, start_weeks_ago=None, step=14):
    """Строит анкеты с заданными суммами (раскладка по пунктам детерминированная)."""
    n = len(totals_phq)
    # последняя анкета — 14 дней назад: в демо пациенту как раз пора заполнять следующую
    start = TODAY - timedelta(days=14 + step * (n - 1))
    out = []
    for i, (p, g) in enumerate(zip(totals_phq, totals_gad)):
        d = (start + timedelta(days=step * i)).isoformat()
        i9 = item9_last if i == n - 1 else 0
        out.append({"date": d, "scale": "phq9", "answers": _spread(p - i9, 8) + [i9]})
        out.append({"date": d, "scale": "gad7", "answers": _spread(g, 7)})
    return out


def _spread(total, k):
    base, rest = divmod(total, k)
    a = [base + (1 if j < rest else 0) for j in range(k)]
    assert max(a) <= 3, (total, k)
    return a


def base(pid, name, age, sex, **kw):
    r = {"patient_id": pid, "name": name, "age": age, "sex": sex, "primary_scale": "gad7",
         "diagnoses": [], "assessments": [], "expected_interval_days": 14,
         "selfreports_missed_consecutive": 0, "diary": [], "adverse_events": [],
         "emergency_button": False, "symptom_checklist": {"mania_or_psychosis": False},
         "therapy": {"current": [], "weeks_on_current": None}, "safety_profile": dict(SAFE),
         "adherence": None, "scenario": ""}
    r.update(kw)
    return r


PATIENTS = [
    base("P-001", "Анна К. (синт.)", 34, "Ж", scenario="1. ГТР подтверждён, данные собраны: Авиандр можно рассмотреть",
         diagnoses=[{"code": "F41.1", "status": "confirmed", "label": "Генерализованное тревожное расстройство"}],
         assessments=series([9, 8, 9], [15, 16, 15]),
         diary=[{"date": ago(2), "text": "Тревожно перед работой, плохо засыпаю"}]),
    base("P-002", "Сергей М. (синт.)", 47, "М", scenario="2. ГТР + противопоказание по инструкции: предложение заблокировано",
         diagnoses=[{"code": "F41.1", "status": "confirmed", "label": "Генерализованное тревожное расстройство"},
                    {"code": "G40.9", "status": "confirmed", "label": "Эпилепсия"}],
         assessments=series([7, 8], [14, 15]),
         safety_profile={**SAFE, "epilepsy_or_organic_brain_lesion": True}),
    base("P-003", "Ольга Д. (синт.)", 29, "Ж", primary_scale="phq9",
         scenario="3. Депрессивная симптоматика без подтверждённого показания: Авиандр не предлагается",
         diagnoses=[{"code": "F32.1", "status": "suspected", "label": "Депрессивный эпизод средней степени (предв.)"}],
         assessments=series([12, 15, 17], [8, 9, 9])),
    base("P-004", "Игорь В. (синт.)", 52, "М", scenario="4. Противопоказания неизвестны: «недостаточно данных», а не «разрешено»",
         diagnoses=[{"code": "F41.1", "status": "confirmed", "label": "Генерализованное тревожное расстройство"}],
         assessments=series([6], [13]),
         safety_profile={"hypersensitivity_aviandr": False, "pregnancy": False, "breastfeeding": False}),
    base("P-005", "Мария С. (синт.)", 23, "Ж", primary_scale="phq9",
         scenario="5. Сообщение о непосредственной опасности: экстренный алерт и эскалация",
         diagnoses=[{"code": "F32.1", "status": "confirmed", "label": "Депрессивный эпизод средней степени"}],
         assessments=series([14, 16, 22], [10, 11, 14], item9_last=3),
         emergency_button=True,
         diary=[{"date": ago(0), "text": "Не вижу выхода, всем было бы легче без меня"}],
         therapy={"current": [{"mnn": "сертралин", "start_date": ago(42)}], "weeks_on_current": 6}),
    base("P-006", "Дмитрий Л. (синт.)", 38, "М", scenario="6. Новое нежелательное явление на фоне Авиандра: решение за врачом",
         diagnoses=[{"code": "F41.1", "status": "confirmed", "label": "Генерализованное тревожное расстройство"}],
         assessments=series([8, 7, 6], [16, 13, 11]),
         adverse_events=[{"date": ago(3), "description": "тошнота по утрам, умеренная", "serious": False, "new": True}],
         therapy={"current": [{"mnn": "Авиандр (действующее вещество — см. карточку)", "start_date": ago(28)}], "weeks_on_current": 4},
         adherence={"confirmed": 50, "missed": 4, "unknown": 2}),
    base("P-007", "Елена Р. (синт.)", 61, "Ж", primary_scale="phq9",
         scenario="7. Пропуски самоотчётов: полнота наблюдения снижена",
         diagnoses=[{"code": "F32.0", "status": "confirmed", "label": "Депрессивный эпизод лёгкой степени"}],
         assessments=series([11, 9], [7, 6], step=14)[:4],
         selfreports_missed_consecutive=3),
    base("P-008", "Алексей Н. (синт.)", 45, "М", scenario="Ответ на терапию: PHQ-9/GAD-7 снижаются",
         diagnoses=[{"code": "F41.1", "status": "confirmed", "label": "Генерализованное тревожное расстройство"}],
         assessments=series([10, 8, 6, 4], [16, 12, 8, 6]),
         therapy={"current": [{"mnn": "Авиандр", "start_date": ago(55)}], "weeks_on_current": 8},
         adherence={"confirmed": 108, "missed": 2, "unknown": 2},
         diary=[{"date": ago(1), "text": "Мыслей о суициде нет, просто иногда устаю"}]),
]


def build():
    out = []
    for p in PATIENTS:
        ev = evaluate_patient(p, drugs=["aviandr"])
        out.append({"record": p, "evaluation": ev})
    return out


if __name__ == "__main__":
    data = build()
    dst = Path(__file__).resolve().parents[1] / "frontend" / "public" / "mock" / "patients.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for d in data:
        e = d["evaluation"]
        print(d["record"]["patient_id"], e["triage_level"],
              [f["rule_id"] for f in e["findings"]], [c["status"] for c in e["drug_checks"]])
