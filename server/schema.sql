-- Схема БД «Компаса». Правило: «неизвестно» хранится как NULL или отсутствие ключа в JSON,
-- а не как false — от этого зависит «недостаточно данных» вместо «противопоказаний нет».

CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    login        TEXT NOT NULL UNIQUE,
    pwd_hash     TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('doctor', 'patient', 'researcher')),
    display_name TEXT NOT NULL,
    patient_id   TEXT REFERENCES patients(id)
);

CREATE TABLE IF NOT EXISTS patients (
    id                     TEXT PRIMARY KEY,
    name                   TEXT NOT NULL,
    age                    INTEGER,
    sex                    TEXT,
    primary_scale          TEXT NOT NULL DEFAULT 'phq9',
    diagnoses              TEXT NOT NULL DEFAULT '[]',   -- JSON [{code, status, label}]
    safety_profile         TEXT NOT NULL DEFAULT '{}',   -- JSON, нет ключа = неизвестно
    symptom_checklist      TEXT NOT NULL DEFAULT '{}',
    context                TEXT NOT NULL DEFAULT '{}',
    concomitant            TEXT NOT NULL DEFAULT '[]',   -- классы сопутствующей терапии для аналитики
    expected_interval_days INTEGER NOT NULL DEFAULT 14,
    missed_consecutive     INTEGER NOT NULL DEFAULT 0,
    emergency_active       INTEGER NOT NULL DEFAULT 0,
    scenario               TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS care_links (
    patient_id TEXT NOT NULL REFERENCES patients(id),
    doctor_id  TEXT NOT NULL REFERENCES users(id),
    deputy_id  TEXT REFERENCES users(id),
    active     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (patient_id, doctor_id)
);

CREATE TABLE IF NOT EXISTS assessments (
    id           INTEGER PRIMARY KEY,
    patient_id   TEXT NOT NULL REFERENCES patients(id),
    date         TEXT NOT NULL,
    scale        TEXT NOT NULL,
    answers      TEXT NOT NULL,                          -- JSON, null = пропуск пункта
    submitted_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_assessments_patient ON assessments(patient_id, date);

CREATE TABLE IF NOT EXISTS diary (
    id           INTEGER PRIMARY KEY,
    patient_id   TEXT NOT NULL REFERENCES patients(id),
    date         TEXT NOT NULL,
    text         TEXT NOT NULL,
    submitted_at TEXT
);

CREATE TABLE IF NOT EXISTS adverse_events (
    id           INTEGER PRIMARY KEY,
    patient_id   TEXT NOT NULL REFERENCES patients(id),
    date         TEXT NOT NULL,
    description  TEXT NOT NULL,
    severity     TEXT CHECK (severity IN ('mild', 'moderate', 'severe')),
    serious      INTEGER NOT NULL DEFAULT 0,
    is_new       INTEGER NOT NULL DEFAULT 1,             -- врач ещё не рассмотрел
    submitted_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_ae_patient ON adverse_events(patient_id, date);

CREATE TABLE IF NOT EXISTS therapy_courses (
    id              TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL REFERENCES patients(id),
    drug_id         TEXT,                                -- id карточки препарата, если есть
    mnn             TEXT NOT NULL,
    indication_code TEXT,
    start_date      TEXT NOT NULL,
    end_date        TEXT,                                -- NULL = курс идёт
    planned_weeks   INTEGER,
    stop_reason     TEXT CHECK (stop_reason IN ('completed', 'adverse_event', 'inefficacy',
                                                'improvement', 'switch', 'lost_to_followup')),
    prescribed_by   TEXT REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS ix_courses_drug ON therapy_courses(drug_id);

CREATE TABLE IF NOT EXISTS intake_marks (
    patient_id TEXT NOT NULL REFERENCES patients(id),
    date       TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('taken', 'missed')),
    reason     TEXT,
    PRIMARY KEY (patient_id, date)
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY,
    patient_id   TEXT NOT NULL REFERENCES patients(id),
    sender_id    TEXT NOT NULL REFERENCES users(id),
    sender_role  TEXT NOT NULL,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    delivered_at TEXT,
    read_at      TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id             INTEGER PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(id),
    doctor_id      TEXT NOT NULL REFERENCES users(id),
    rule_id        TEXT NOT NULL,
    rule_version   TEXT,
    engine_version TEXT,
    action         TEXT NOT NULL,
    comment        TEXT,
    evidence       TEXT,
    at             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id               TEXT PRIMARY KEY,
    patient_id       TEXT NOT NULL REFERENCES patients(id),
    rule_id          TEXT NOT NULL,
    priority         TEXT NOT NULL,
    title            TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'created'
                     CHECK (status IN ('created', 'delivered', 'accepted', 'closed')),
    assigned_to      TEXT NOT NULL REFERENCES users(id),
    escalation_level INTEGER NOT NULL DEFAULT 0,
    saved_at         TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    delivered_at     TEXT,
    accepted_at      TEXT,
    accepted_by      TEXT,
    closed_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_open ON alerts(status, assigned_to);

CREATE TABLE IF NOT EXISTS alert_events (
    id       INTEGER PRIMARY KEY,
    alert_id TEXT NOT NULL REFERENCES alerts(id),
    status   TEXT NOT NULL,
    at       TEXT NOT NULL,
    user_id  TEXT,
    note     TEXT
);

CREATE TABLE IF NOT EXISTS self_reports (
    idempotency_key TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL REFERENCES patients(id),
    received_at     TEXT NOT NULL,
    response        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY,
    user_id    TEXT,
    role       TEXT,
    action     TEXT NOT NULL,
    patient_id TEXT,
    allowed    INTEGER NOT NULL,
    at         TEXT NOT NULL
);

-- Загруженные врачом документы и результат извлечения (для аудита и воспроизводимости)
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    uploaded_by TEXT NOT NULL REFERENCES users(id),
    text        TEXT NOT NULL,
    extraction  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Направление к психиатру — действие врача; необходимость и срочность — две независимые оси
CREATE TABLE IF NOT EXISTS referrals (
    id         INTEGER PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    doctor_id  TEXT NOT NULL REFERENCES users(id),
    necessity  TEXT NOT NULL CHECK (necessity IN ('mandatory', 'desirable')),
    urgency    TEXT NOT NULL CHECK (urgency IN ('emergency', 'urgent', 'planned')),
    reason     TEXT NOT NULL,
    rule_id    TEXT,
    status     TEXT NOT NULL DEFAULT 'issued' CHECK (status IN ('issued', 'scheduled', 'completed', 'cancelled')),
    note       TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Согласие пациента на обработку данных (версия текста фиксируется)
CREATE TABLE IF NOT EXISTS consents (
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    version     TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    user_id     TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (patient_id, version)
);
