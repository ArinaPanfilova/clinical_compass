// Типы повторяют выход kompas_core.evaluate_patient (см. docs/API_CONTRACT.md)

export type Priority = 'emergency' | 'urgent' | 'planned' | 'info'
export type Routing = 'mandatory' | 'desirable' | null
export type Kind = 'alert' | 'routing' | 'therapy_warning' | 'review_task' | 'data_quality' | 'scope'

export interface Finding {
  rule_id: string
  rule_version: string
  rule_status: 'draft' | 'approved'
  kind: Kind
  priority: Priority
  routing: Routing
  title: string
  message: string
  patient_message: string | null
  auto_actions: string[]
  requires_doctor_confirmation: boolean
  sources: string[]
  evidence: Record<string, unknown>
  fired_on: 'true' | 'unknown'
}

export interface DrugCheck {
  drug_id: string
  trade_name: string
  status: 'can_be_considered' | 'not_applicable' | 'insufficient_data' | 'card_not_verified'
  reasons: string[]
  unknown_facts: string[]
  cautions: string[]
  interactions: string[]
  source: string
  verification_level: 'none' | 'secondary' | 'grls_team_checked' | 'grls_verified'
  warnings: string[]
}

export interface ScalePoint {
  date: string
  scale_id: string
  total: number | null
  prorated: boolean
  category: string | null
  category_label: string | null
  safety_item_value: number | null
  missing_items: number[]
  flags: string[]
}

export interface Change {
  baseline: number
  current: number
  delta: number
  direction: 'improved' | 'worsened' | 'no_meaningful_change'
  reliable: boolean | null
  response: boolean
  remission: boolean
  thresholds: { mcid: number; reliable_change: number | null; mcid_source: string }
}

export interface Evaluation {
  patient_id: string
  engine_version: string
  triage_level: Priority | 'none'
  findings: Finding[]
  drug_checks: DrugCheck[]
  facts: Record<string, unknown>
  details: {
    scales: Record<string, ScalePoint[]>
    changes: Record<string, Change>
    trends: Record<string, { n_points: number; slope_per_week: number | null; coverage: number; max_gap_days: number | null; note: string }>
    text: { date: string; flagged: boolean; matched: string[]; negated: string[] }[]
  }
  disclaimer: string
  elapsed_ms: number
}

export interface PatientRecord {
  patient_id: string
  name: string
  age: number
  sex: string
  scenario: string
  primary_scale: 'phq9' | 'gad7'
  diagnoses: { code: string; status: string; label?: string }[]
  diary: { date: string; text: string }[]
  adverse_events: { date: string; description: string; serious: boolean; new: boolean }[]
  therapy: { current: { mnn: string; start_date?: string }[]; weeks_on_current: number | null }
  safety_profile: Record<string, boolean | null>
  adherence: { confirmed: number; missed: number; unknown: number } | null
  selfreports_missed_consecutive: number
}

export interface PatientBundle {
  record: PatientRecord
  evaluation: Evaluation
  link?: 'lead' | 'deputy' | 'self'
  alerts?: Alert[]
  decisions?: Decision[]
  referrals?: Referral[]
}

export interface Decision {
  patient_id: string
  finding_rule_id: string
  action: 'confirm' | 'reject' | 'modify'
  comment?: string | null
  at: string
}

export type Role = 'doctor' | 'patient' | 'researcher'

export interface Consent { version: string; title: string; points: string[]; basis: string }

export interface User {
  id: string
  role: Role
  display_name: string
  patient_id: string | null
  consent_required?: boolean
  consent?: Consent | null
}

export interface Referral {
  id: number
  patient_id: string
  doctor_id: string
  necessity: 'mandatory' | 'desirable'
  urgency: 'emergency' | 'urgent' | 'planned'
  reason: string
  rule_id: string | null
  status: 'issued' | 'scheduled' | 'completed' | 'cancelled'
  note: string | null
  created_at: string
  updated_at: string
}

export interface Alert {
  id: string
  patient_id: string
  patient_name: string
  rule_id: string
  priority: Priority
  title: string
  status: 'created' | 'delivered' | 'accepted' | 'closed'
  assigned_to: string
  escalation_level: number
  saved_at: string
  created_at: string
  delivered_at: string | null
  accepted_at: string | null
  accepted_by: string | null
  closed_at: string | null
  history: { status: string; at: string; user_id: string | null; note: string | null }[]
}

export interface Message {
  id: number
  patient_id: string
  sender_id: string
  sender_role: Role
  text: string
  created_at: string
  delivered_at: string | null
  read_at: string | null
}

export interface Evidence { start: number; end: number; quote: string }

export interface DocumentExtraction {
  document_id: number
  extraction: {
    diagnoses: { code: string; status: 'confirmed' | 'suspected'; evidence: Evidence }[]
    medications: { mnn: string; dose_mg: number | null; status: 'current' | 'cancelled'; evidence: Evidence }[]
    allergies: { name: string; evidence: Evidence }[] | null
    safety: Record<string, { value: boolean | null; evidence: Evidence | null }>
    document_date: string | null
    status: 'extracted_unverified'
  }
  diff: { key: string; current: boolean | null; extracted: boolean; evidence: Evidence; kind: 'new' | 'same' | 'conflict' }[]
}
