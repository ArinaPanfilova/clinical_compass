// Тексты анкет — дословно по валидированным русскоязычным версиям (Приложения к статьям):
// PHQ-9 — Золотарева А.А. Клиническая и специальная психология. 2023;12(4):107–121.
//         DOI 10.17759/cpse.2023120406 (n = 1800, α = 0,89);
// GAD-7 — Золотарева А.А. Консультативная психология и психотерапия. 2023;31(4):31–46.
//         DOI 10.17759/cpp.2023310402 (n = 1130, α = 0,93).
// Менять формулировки нельзя: другой текст — другой инструмент. Заглавная буква — только для отображения.

export const INSTRUCTION = 'Оцените, пожалуйста, насколько часто следующие проблемы беспокоили вас в течение прошедших двух недель.'

export const PHQ9_OPTIONS = ['Совсем нет', 'В течение нескольких дней', 'Более, чем половину этого времени', 'Почти каждый день']
export const GAD7_OPTIONS = ['Совсем нет', 'В течение нескольких дней', 'Более чем половину этого времени', 'Почти каждый день']

export const PHQ9 = [
  'Снижение интереса и удовольствия от привычных дел',
  'Чувство подавленности или безнадежности',
  'Проблемы со сном (неспособность заснуть, раннее пробуждение или слишком долгий сон)',
  'Чувство усталости или недостатка энергии',
  'Плохой аппетит или переедание',
  'Плохое мнение о себе или чувство, что не смог оправдать ожиданий моей семьи',
  'Проблемы с концентрацией внимания (например, при чтении газеты или просмотре телевизионной передачи)',
  'Замедленность движений или речи, которая стала заметна другим людям, или, напротив, суетливость, когда движения и речь стали более быстрыми и беспокойными',
  'Мысли о том, что мне бы хотелось умереть или причинить себе боль',
]

export const GAD7 = [
  'Чувство тревоги или раздражения',
  'Неспособность справиться со своим беспокойством',
  'Чрезмерное беспокойство по разным поводам',
  'Неспособность расслабляться',
  'Ощущение такого беспокойства, что трудно найти себе место',
  'Склонность быстро испытывать злость или раздражительность',
  'Чувство страха, как будто может случиться что-то ужасное',
]

export const SCALE_SOURCES = {
  phq9: 'PHQ-9, русскоязычная версия: Золотарева А.А., 2023, DOI 10.17759/cpse.2023120406',
  gad7: 'GAD-7, русскоязычная версия: Золотарева А.А., 2023, DOI 10.17759/cpp.2023310402',
}

export const SAFETY_LABELS: Record<string, string> = {
  hypersensitivity_aviandr: 'Гиперчувствительность к Авиандру',
  epilepsy_or_organic_brain_lesion: 'Эпилепсия / органическое поражение мозга',
  maoi_within_2_weeks: 'Ингибиторы МАО (≤ 2 нед.)',
  renal_gfr_below_60: 'СКФ < 60 мл/мин',
  hepatic_insufficiency: 'Печёночная недостаточность',
  pregnancy: 'Беременность',
  breastfeeding: 'Грудное вскармливание',
  cardiovascular_disease: 'Сердечно-сосудистые заболевания',
  endocrine_disorder: 'Диабет / эндокринные заболевания',
  substance_dependence: 'Алкогольная или наркотическая зависимость',
  lactose_intolerance: 'Непереносимость лактозы',
  drives_vehicles: 'Управляет транспортом',
}

export const ALL_SAFETY_KEYS = Object.keys(SAFETY_LABELS)

export const BANDS: Record<string, { min: number; max: number; label: string }[]> = {
  phq9: [
    { min: 0, max: 4, label: 'минимальная' }, { min: 5, max: 9, label: 'лёгкая' },
    { min: 10, max: 14, label: 'умеренная' }, { min: 15, max: 19, label: 'умеренно тяжёлая' },
    { min: 20, max: 27, label: 'тяжёлая' },
  ],
  gad7: [
    { min: 0, max: 4, label: 'минимальная' }, { min: 5, max: 9, label: 'лёгкая' },
    { min: 10, max: 14, label: 'умеренная' }, { min: 15, max: 21, label: 'тяжёлая' },
  ],
}

export const DRUG_STATUS: Record<string, { label: string; tone: string }> = {
  can_be_considered: { label: 'Можно рассмотреть', tone: 'ok' },
  not_applicable: { label: 'Не подходит', tone: 'block' },
  insufficient_data: { label: 'Недостаточно данных', tone: 'unknown' },
  card_not_verified: { label: 'Карточка не сверена', tone: 'unknown' },
}

export const FACT_LABELS: Record<string, string> = {
  'diagnosis.confirmed': 'подтверждение диагноза',
  'patient.age': 'возраст',
  'context.post_covid': 'связь с перенесённым COVID-19',
  'context.mild_to_moderate': 'степень тяжести (лёгкая/средняя)',
  ...Object.fromEntries(Object.entries(SAFETY_LABELS).map(([k, v]) => [`safety.${k}`, v.toLowerCase()])),
}

// Демо-аккаунты (пароль у всех — demo). Без сервера вход локальный, только для просмотра.
export const DEMO_ACCOUNTS: { login: string; name: string; note: string; role: 'doctor' | 'patient' | 'researcher'; id: string; patient_id: string | null }[] = [
  { login: 'ivanova', name: 'Иванова Е. А.', note: 'Лечащий врач: 8 клинических сценариев', role: 'doctor', id: 'doc-ivanova', patient_id: null },
  { login: 'petrov', name: 'Петров С. В.', note: 'Заместитель: получает непринятые алерты', role: 'doctor', id: 'doc-petrov', patient_id: null },
  { login: 'anna', name: 'Анна К.', note: 'Пациентка, ГТР: Авиандр можно рассмотреть', role: 'patient', id: 'pat-P-001', patient_id: 'P-001' },
  { login: 'maria', name: 'Мария С.', note: 'Пациентка, экстренный сценарий', role: 'patient', id: 'pat-P-005', patient_id: 'P-005' },
  { login: 'alexey', name: 'Алексей Н.', note: 'Пациент на Авиандре, отмечает приём', role: 'patient', id: 'pat-P-008', patient_id: 'P-008' },
  { login: 'researcher', name: 'Исследователь', note: 'Обезличенная аналитика Авиандра', role: 'researcher', id: 'res-1', patient_id: null },
]

export const PRIORITY_LABEL: Record<string, string> = { emergency: 'Экстренно', urgent: 'Срочно', planned: 'Планово', info: 'Для сведения' }
