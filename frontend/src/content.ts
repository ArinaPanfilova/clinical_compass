// ВНИМАНИЕ: тексты пунктов — рабочий перевод для прототипа.
// Перед апробацией заменить дословно валидированными русскими версиями:
// PHQ-9 — Золотарева А.А., 2023 (DOI 10.17759/cpse.2023120406);
// GAD-7 — Золотарева А.А., 2023 (DOI 10.17759/cpp.2023310402).

export const OPTIONS = ['Ни разу', 'Несколько дней', 'Более половины дней', 'Почти каждый день']

export const PHQ9 = [
  'Мало интереса или удовольствия от того, чем вы занимаетесь',
  'Подавленное настроение, чувство безнадёжности',
  'Трудности с засыпанием, прерывистый сон или слишком долгий сон',
  'Чувство усталости или упадок сил',
  'Плохой аппетит или переедание',
  'Плохое мнение о себе: чувство, что вы неудачник или подвели себя или семью',
  'Трудно сосредоточиться, например, на чтении или просмотре фильма',
  'Движения или речь замедлились так, что окружающие могли заметить, или, наоборот, вы были настолько суетливы, что не могли усидеть на месте',
  'Мысли о том, что лучше было бы умереть, или о том, чтобы причинить себе вред',
]

export const GAD7 = [
  'Нервозность, тревога или ощущение «на взводе»',
  'Не получалось остановить или контролировать беспокойство',
  'Чрезмерное беспокойство по разным поводам',
  'Трудно расслабиться',
  'Такое беспокойство, что трудно усидеть на месте',
  'Легко раздражаетесь или злитесь',
  'Страх, будто может случиться что-то ужасное',
]

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
