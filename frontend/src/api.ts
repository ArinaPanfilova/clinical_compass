import type { Alert, Decision, DocumentExtraction, Message, PatientBundle, Referral, User } from './types'

// Два режима:
// live — работает сервер (python -m server) по адресу /api: вход, роли, алерты, сообщения;
// demo — сервера нет, данные из public/mock/*.json, правила не пересчитываются.
// Клиническая логика живёт только на сервере: фронтенд её не дублирует.

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api'

export type Mode = 'live' | 'demo'

// Токен — в sessionStorage: у каждой вкладки свой вход (врач и пациент рядом в демо)
const KEY = 'kompas.token'
let token: string | null = (() => { try { return sessionStorage.getItem(KEY) } catch { return null } })()

export function setToken(t: string | null) {
  token = t
  try { if (t) sessionStorage.setItem(KEY, t); else sessionStorage.removeItem(KEY) } catch { /* приватный режим */ }
}

export const hasToken = () => token !== null

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function req<T>(path: string, init: { method?: string; json?: unknown; headers?: Record<string, string> } = {}): Promise<T> {
  const headers: Record<string, string> = { ...init.headers }
  if (token) headers.Authorization = `Bearer ${token}`
  if (init.json !== undefined) headers['Content-Type'] = 'application/json'
  const r = await fetch(`${BASE}${path}`, {
    method: init.method ?? 'GET', headers,
    body: init.json !== undefined ? JSON.stringify(init.json) : undefined,
  })
  if (!r.ok) {
    const detail = await r.json().then(j => j.detail, () => null)
    throw new ApiError(r.status, typeof detail === 'string' ? detail : `Ошибка ${r.status}`)
  }
  return r.json() as Promise<T>
}

export async function detectMode(): Promise<Mode> {
  try {
    const r = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(1500) })
    if (r.ok && r.headers.get('content-type')?.includes('json')) return 'live'
  } catch { /* сервер недоступен */ }
  return 'demo'
}

export async function loadMockPatients(): Promise<PatientBundle[]> {
  return (await fetch('./mock/patients.json')).json()
}

export interface SelfReportBody {
  questionnaires: { scale: 'phq9' | 'gad7'; answers: (number | null)[] }[]
  diary_text?: string
  adverse_event?: string
  adverse_event_serious?: boolean
  emergency?: boolean
}

export interface SelfReportResult { saved_at: string; evaluation: PatientBundle['evaluation']; patient_messages: string[] }

export const api = {
  login: (login: string, password: string) =>
    req<{ token: string; user: User }>('/auth/login', { method: 'POST', json: { login, password } }),
  me: () => req<User>('/me'),
  patients: () => req<PatientBundle[]>('/patients'),
  patient: (pid: string) => req<PatientBundle>(`/patients/${pid}`),
  // Ключ идемпотентности: повтор после обрыва связи не создаст второй самоотчёт и второй алерт
  selfReport: (pid: string, body: SelfReportBody, key: string) =>
    req<SelfReportResult>(`/patients/${pid}/self-report`, { method: 'POST', json: body, headers: { 'Idempotency-Key': key } }),
  decide: (pid: string, finding_rule_id: string, action: Decision['action'], comment?: string) =>
    req<Decision>(`/patients/${pid}/decisions`, { method: 'POST', json: { finding_rule_id, action, comment } }),
  alertAction: (id: string, action: 'ack' | 'accept' | 'close') => req<Alert>(`/alerts/${id}/${action}`, { method: 'POST' }),
  messages: (pid: string) => req<Message[]>(`/patients/${pid}/messages`),
  sendMessage: (pid: string, text: string) => req<Message>(`/patients/${pid}/messages`, { method: 'POST', json: { text } }),
  readMessage: (id: number) => req<Message>(`/messages/${id}/read`, { method: 'POST' }),
  intake: (pid: string, status: 'taken' | 'missed', reason?: string) =>
    req<{ adherence: PatientBundle['record']['adherence'] }>(`/patients/${pid}/intake`, { method: 'POST', json: { status, reason } }),
  analytics: <T,>(q: Record<string, string | undefined>) => {
    const params = new URLSearchParams(Object.entries(q).filter((e): e is [string, string] => !!e[1]))
    return req<T>(`/analytics/aviandr?${params}`)
  },
  // Извлечение ничего не меняет в карточке; в профиль попадает только подтверждённое врачом
  extractDocument: (pid: string, text: string) =>
    req<DocumentExtraction>(`/patients/${pid}/documents/extract`, { method: 'POST', json: { text } }),
  updateSafety: (pid: string, facts: Record<string, boolean | null>, source: 'document' | 'manual', document_id?: number) =>
    req<PatientBundle>(`/patients/${pid}/safety-profile`, { method: 'POST', json: { facts, source, document_id } }),
  issueReferral: (pid: string, body: Pick<Referral, 'necessity' | 'urgency' | 'reason' | 'rule_id'>) =>
    req<Referral>(`/patients/${pid}/referrals`, { method: 'POST', json: body }),
  referralStatus: (id: number, status: Referral['status'], note?: string) =>
    req<Referral>(`/referrals/${id}/status`, { method: 'POST', json: { status, note } }),
  acceptConsent: (version: string) => req<{ ok: boolean }>('/consent', { method: 'POST', json: { version } }),
  reset: () => req<{ ok: boolean }>('/demo/reset', { method: 'POST' }),
  // SSE: EventSource не умеет заголовки, поэтому токен — параметром
  stream: () => new EventSource(`${BASE}/events/stream?token=${encodeURIComponent(token ?? '')}`),
}

export const newKey = () =>
  (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`)
