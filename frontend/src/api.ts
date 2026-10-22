import type { PatientBundle } from './types'

// Два режима:
// live — работает сервер правил (api_stub или бэкенд команды) по адресу /api;
// demo — сервера нет, данные из public/mock/patients.json, правила не пересчитываются.
// Клиническая логика живёт только на сервере: фронтенд её не дублирует.

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api'

export type Mode = 'live' | 'demo'

export async function loadPatients(): Promise<{ mode: Mode; patients: PatientBundle[] }> {
  try {
    const r = await fetch(`${BASE}/patients`, { signal: AbortSignal.timeout(1500) })
    if (r.ok && r.headers.get('content-type')?.includes('json')) {
      return { mode: 'live', patients: await r.json() }
    }
  } catch { /* сервер недоступен — демо-режим */ }
  const r = await fetch('./mock/patients.json')
  return { mode: 'demo', patients: await r.json() }
}

export interface SelfReportBody {
  questionnaires: { scale: 'phq9' | 'gad7'; answers: (number | null)[] }[]
  diary_text?: string
  medication_taken?: 'taken' | 'missed' | 'unknown'
  adverse_event?: string
  adverse_event_serious?: boolean
  emergency?: boolean
}

export async function submitSelfReport(pid: string, body: SelfReportBody) {
  const r = await fetch(`${BASE}/patients/${pid}/self-report`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error((await r.json()).detail ?? `Ошибка ${r.status}`)
  return r.json() as Promise<{ saved_at: string; evaluation: PatientBundle['evaluation']; patient_messages: string[] }>
}

export async function sendDecision(pid: string, finding_rule_id: string, action: string, comment?: string) {
  const r = await fetch(`${BASE}/patients/${pid}/decisions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ finding_rule_id, action, comment }),
  })
  if (!r.ok) throw new Error((await r.json()).detail ?? `Ошибка ${r.status}`)
  return r.json()
}

export async function resetDemo() {
  await fetch(`${BASE}/demo/reset`, { method: 'POST' })
}
