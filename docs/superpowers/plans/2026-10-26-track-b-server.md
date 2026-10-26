# Трек Б: сервер `server/` — план реализации

> Выполняется в основной сессии (inline, superpowers:executing-plans), шаги TDD. Полный код тестов —
> в файлах `tests/test_server_*.py`, они пишутся первым шагом каждой задачи и служат спецификацией.

**Goal:** FastAPI + SQLite сервер с ролями врач/пациент/исследователь, алерт-конвейером
(транзакция, идемпотентность, SSE, эскалация), сообщениями, приверженностью и эндпоинтом аналитики.

**Architecture:** `server/` — пакет поверх `kompas_core`. Каждая HTTP-ручка открывает своё
соединение SQLite (WAL). Логика вне HTTP — в чистых функциях модулей (`records`, `courses`,
`alerts`, `access`), которые тестируются напрямую; HTTP проверяется через `TestClient`.
API под префиксом `/api`, собранный фронтенд раздаётся с `/`.

**Tech Stack:** FastAPI 0.162, Starlette, pydantic 2, stdlib `sqlite3`/`hmac`/`hashlib`, pytest + httpx.

Спек: `docs/superpowers/specs/2026-10-26-kompas-tz-completion-design.md`, блоки 1 и 3.

## Файлы

| Файл | Ответственность |
|---|---|
| `server/schema.sql` | Схема БД |
| `server/db.py` | Соединение с pragma, создание схемы, транзакция |
| `server/auth.py` | Хэш пароля, токен `user_id.exp.sig` |
| `server/access.py` | `can_view_patient`, список пациентов врача, аудит |
| `server/records.py` | `build_record(conn, pid)` в формате контракта |
| `server/courses.py` | `build_courses(conn, drug_id)` — курсы для `aviandr_report` |
| `server/alerts.py` | Создание алертов, дедупликация, `Broker`, `escalate_due`, `pending_for` |
| `server/seed.py` | Демо-пользователи, сценарные пациенты, когорта Авиандра |
| `server/app.py` | `create_app(db_path, …)` — эндпоинты, SSE, фоновая эскалация, статика |
| `server/__main__.py` | `python -m server` |
| `tests/test_server_records.py` | Сборка записи и курсов из БД |
| `tests/test_server_access.py` | Вход, матрица доступа, аудит |
| `tests/test_server_alerts.py` | Транзакция, идемпотентность, дедупликация, эскалация, ack/accept/close |
| `tests/test_server_features.py` | Сообщения, отметки приёма, аналитика по ролям, демо-сброс |

## Задачи

1. **БД, запись пациента, сид** — тесты `test_server_records.py` (сценарные пациенты из
   `synthetic/demo_patients.PATIENTS` после записи в БД и сборки дают тот же `evaluate_patient`
   по `triage_level` и набору `rule_id`; неизвестное в профиле безопасности остаётся неизвестным;
   курсы Авиандра собираются с визитами по неделям и счётчиками приёма) → `schema.sql`, `db.py`,
   `records.py`, `courses.py`, `seed.py`.
2. **Вход и доступ** — тесты `test_server_access.py` (неверный пароль 401; токен истёк/подделан 401;
   матрица роль × эндпоинт × свой/чужой; заместитель видит пациента только при эскалированном
   на него открытом алерте; каждый отказ в `audit_log`) → `auth.py`, `access.py`, ручки чтения в `app.py`.
3. **Алерт-конвейер** — тесты `test_server_alerts.py` (самоотчёт с п.9 = 2 создаёт срочный алерт
   на лечащего врача, `saved_at ≤ created_at`; повтор с тем же `Idempotency-Key` не создаёт данных
   и алертов; повторный самоотчёт не дублирует открытый алерт по тому же правилу; невалидная анкета
   422 и ничего не записано; `escalate_due` переназначает непринятый срочный алерт заместителю, а
   принятый — нет; `pending_for` возвращает недоставленные; ack/accept/close пишут метки времени;
   решение врача закрывает алерт) → `alerts.py`, ручки самоотчёта, алертов, решений, SSE.
4. **Сообщения, приём, аналитика** — тесты `test_server_features.py` (пациент пишет → врач видит,
   `delivered_at` при чтении ленты получателем, `read_at` по `/read`; чужой пациент 403; отметка
   приёма меняет `adherence` в записи; аналитика: врач — только свои курсы `k_min=1`,
   исследователь — все, `k_min=5`, пациент 403; демо-сброс возвращает исходное состояние) →
   ручки в `app.py`.
5. **Запуск** — `server/__main__.py`, раздача `frontend/dist`, правка прокси Vite (без rewrite),
   README; ручная проверка `python -m server` + `curl /api/health`.

После каждой задачи: полный `pytest -q`, коммит.
