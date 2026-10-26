// Отчёт аналитики Авиандра — ответ GET /api/analytics/aviandr.
// Формат: docs/API_CONTRACT.md («Курсы для аналитики»), код: kompas_core/analytics.py::aviandr_report.
// Клиническую логику фронтенд не повторяет: только показывает готовые числа.

export type ScaleId = 'gad7' | 'phq9'
export type OutcomeGroup = 'continued' | 'stopped_ae' | 'stopped_inefficacy' | 'stopped_other'
export type StopReason = 'completed' | 'adverse_event' | 'inefficacy' | 'improvement' | 'switch' | 'lost_to_followup'
export type AdherenceBand = '≥80%' | '50–79%' | '<50%'

/** Счётчик. В режиме исследователя (k_min > 1) значения 1…k−1 приходят как null. */
export type MaskedCount = number | null
/** 95 % ДИ Вильсона долями 0…1 (pct рядом — в процентах). */
export type Ci95 = [number, number]

/** Фильтры экрана. Пустая строка или отсутствие ключа — «все»; 'none' — «нет». */
export interface AnalyticsQuery {
  scale: ScaleId
  start_from?: string
  start_to?: string
  age_min?: string
  age_max?: string
  sex?: string
  indication?: string
  comorbidity?: string
  concomitant?: string
}

export interface Rate {
  n: MaskedCount
  pct: number | null
  ci95: Ci95 | null
  /** true — ячейка скрыта (n < k_min) */
  hidden?: boolean
}

export interface Kpis {
  assigned: MaskedCount
  active: MaskedCount
  completed: MaskedCount
  discontinued: MaskedCount
  by_reason: Partial<Record<Exclude<StopReason, 'completed'>, MaskedCount>>
}

export interface TrajectoryPoint {
  week: number
  n: number | null
  median: number | null
  q1: number | null
  q3: number | null
  /** true — точка скрыта: меньше k_min человек */
  hidden: boolean
}

export interface ResponseRates {
  scale: ScaleId
  denominator: number
  response: Rate
  mcid: Rate
  remission: Rate
  definitions: { response: string; mcid: string; remission: string }
}

export interface Adherence {
  courses_with_data: number
  median_pct: number | null
  bands: Record<AdherenceBand, MaskedCount>
  unknown_share_pct: number | null
  note: string
}

export interface AeTermRow {
  term: string
  mild: MaskedCount
  moderate: MaskedCount
  severe: MaskedCount
  /** тяжесть не оценена (≠ лёгкая) */
  unknown: MaskedCount
  total: MaskedCount
}

export interface Safety {
  courses: number
  with_ae: Rate
  serious: Rate
  stopped_due_to_ae: Rate
  by_term: AeTermRow[]
  note: string
}

export interface BenefitIndex {
  scale: ScaleId
  value_pct: number | null
  ci95: Ci95 | null
  numerator: number | null
  denominator: number
  components: { responders: number; with_harm: number }
  formula: string
  hidden?: boolean
}

export interface Composition {
  age: Record<string, MaskedCount>
  sex: Record<string, MaskedCount>
  indication: Record<string, MaskedCount>
  comorbidity: Record<string, MaskedCount>
  concomitant: Record<string, MaskedCount>
}

export interface ReportLabels {
  stop_reasons: Record<StopReason, string>
  groups: Record<OutcomeGroup, string>
}

interface ReportBase {
  k_min: number
  scale: ScaleId
  /** Методологическая оговорка — показывается всегда */
  caveat: string
  /** own — свои курсы врача; pseudonymized — все курсы обезличенно */
  view?: 'own' | 'pseudonymized'
  synthetic?: boolean
  drug?: string
}

export interface AviandrReportFull extends ReportBase {
  n: number
  empty: false
  suppressed: false
  kpis: Kpis
  composition: Composition
  trajectories: Record<OutcomeGroup, TrajectoryPoint[]>
  response: ResponseRates
  adherence: Adherence
  safety: Safety
  benefit_index: BenefitIndex
  labels: ReportLabels
}

export interface AviandrReportEmpty extends ReportBase {
  n: 0
  empty: true
  suppressed: false
}

export interface AviandrReportSuppressed extends ReportBase {
  n: null
  suppressed: true
  message: string
  empty?: undefined
}

export type AviandrReport = AviandrReportFull | AviandrReportEmpty | AviandrReportSuppressed
