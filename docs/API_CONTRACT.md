# Контракт между ядром правил, бэкендом и фронтендом

Ядро `kompas_core` — чистая библиотека без сети и БД. Бэкенд (роль 3) хранит данные,
проверяет права и вызывает одну функцию:

```python
from kompas_core import evaluate_patient
result = evaluate_patient(record, drugs=["aviandr"])
```

Эталонная реализация эндпоинтов — `api_stub/main.py` (без авторизации и БД, только для демо).

## Вход: `record`

```jsonc
{
  "patient_id": "P-001",
  "age": 34,                          // null = неизвестно
  "primary_scale": "gad7",            // по какой шкале оценивать ответ на терапию
  "diagnoses": [{"code": "F41.1", "status": "confirmed" /* или suspected */}],
  "assessments": [
    {"date": "2026-10-09", "scale": "phq9", "answers": [1,1,0,2,1,0,1,0,0]},  // null = пропуск
    {"date": "2026-10-09", "scale": "gad7", "answers": [2,2,2,2,2,2,3]}
  ],
  "expected_interval_days": 14,
  "selfreports_missed_consecutive": 0,
  "diary": [{"date": "2026-10-21", "text": "..."}],          // null = дневник не ведётся
  "adverse_events": [{"date": "...", "description": "...", "serious": false, "new": true}],
  "emergency_button": false,
  "symptom_checklist": {"mania_or_psychosis": false},
  "therapy": {"current": [{"mnn": "сертралин", "start_date": "..."}], "weeks_on_current": 6},
  "safety_profile": {"pregnancy": false, "epilepsy_or_organic_brain_lesion": null},  // null/нет ключа = неизвестно
  "context": {"post_covid": true, "mild_to_moderate": true}
}
```

**Правило для БД: «неизвестно» хранится как NULL, а не как false.** От этого зависит, скажет
система «недостаточно данных» или ошибочно «противопоказаний нет».

## Выход

```jsonc
{
  "triage_level": "emergency | urgent | planned | info | none",
  "findings": [{
    "rule_id": "SAFE-002", "rule_version": "0.1", "rule_status": "draft",
    "kind": "alert | routing | therapy_warning | review_task | data_quality | scope",
    "priority": "emergency | urgent | planned | info",
    "routing": "mandatory | desirable | null",
    "title": "...", "message": "...", "patient_message": "... | null",
    "auto_actions": ["notify_doctor", ...],          // только информирование, см. ALLOWED_AUTO_ACTIONS
    "requires_doctor_confirmation": true,            // всегда true
    "sources": ["..."], "evidence": {"phq9.item9": 2}
  }],
  "drug_checks": [{"status": "can_be_considered | not_applicable | insufficient_data | card_not_verified", ...}],
  "details": {"scales": {...}, "changes": {...}, "trends": {...}, "text": [...]},
  "elapsed_ms": 2.1
}
```

## Что бэкенду сохранить для метрик и аудита

* Для каждого решения врача: `rule_id`, `rule_version`, `engine_version`, `evidence` на момент решения, действие, причина (обязательна при отклонении/изменении), время, врач.
* Для алертов — метки времени этапов: `saved_at` (данные пациента записаны) → `created_at` → `delivered_at` → `accepted_at` → `action_at` → `closed_at`. Из них считается «время доставки алерта» из ТЗ.
* Версию паспорта шкалы при каждом расчёте (`passport_version`).

## Эндпоинты заглушки

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/patients` | все пациенты с оценкой |
| GET | `/patients/{id}` | карточка + журнал решений |
| POST | `/patients/{id}/self-report` | самоотчёт пациента → пересчёт → алерты |
| POST | `/patients/{id}/decisions` | решение врача по находке |
| GET | `/alerts` | журнал алертов |
| POST | `/demo/reset` | сброс демо |

## Курсы для аналитики (`kompas_core.analytics.aviandr_report`)

```python
from kompas_core import aviandr_report
report = aviandr_report(courses, filters={"sex": "Ж", "indication": "F41.1"}, scale="gad7", k_min=5)
```

Курс — словарь: `course_id`, `patient_key`, `doctor_id`, `drug_id`, `age`, `sex` (`Ж|М`),
`indication` (`F41.1|F43.2`), `comorbidities` (`[]` = нет), `concomitant` (`[]` = нет),
`start_date`, `end_date` (`null` = идёт), `planned_weeks`, `stop_reason`
(`null|completed|adverse_event|inefficacy|improvement|switch|lost_to_followup`),
`visits` (`[{week, gad7, phq9}]`, `null` = анкета не пришла), `intake` (`{taken, missed, unknown}`),
`adverse_events` (`[{term, severity: mild|moderate|severe, serious, week}]`).

Фильтры: `start_from`, `start_to`, `age_min`, `age_max`, `sex`, `indication`, `comorbidity`,
`concomitant` (`none` = нет), `doctor_id`. `k_min > 1` — режим исследователя: выборка меньше k
скрывается целиком, ячейки 1…k−1 заменяются на `null`.

Индекс устойчивой пользы = курсы с ответом (снижение ≥ 50 % на последнем наблюдении) без серьёзных
НЯ и без отмены из-за НЯ / все начатые курсы с исходным измерением (ITT), 95 % ДИ Вильсона.
Это описание наблюдения, не оценка эффективности: контрольной группы нет.
