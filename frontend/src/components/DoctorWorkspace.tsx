import { useCallback, useEffect, useState } from 'react'
import { api, loadMockPatients, type Mode } from '../api'
import { PRIORITY_LABEL } from '../content'
import type { Alert, Decision, Finding, Message, PatientBundle, User } from '../types'
import { DoctorView, shortName } from './DoctorView'

// Рабочее место врача: список пациентов с сервера, живая доставка алертов и сообщений (SSE).
// Полученный алерт сразу подтверждается серверу как «доставлен»; «принят» — только действием врача.

type Toast = { id: string; pid: string; alert?: Alert; message?: Message }

function beep(urgent: boolean) {
  try {
    const ctx = new AudioContext()
    const o = ctx.createOscillator(); const g = ctx.createGain()
    o.frequency.value = urgent ? 880 : 660
    g.gain.setValueAtTime(0.12, ctx.currentTime); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5)
    o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.5)
  } catch { /* звук недоступен — остаётся визуальный сигнал */ }
}

export function DoctorWorkspace({ user, mode }: { user: User; mode: Mode }) {
  const [patients, setPatients] = useState<PatientBundle[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [msgTick, setMsgTick] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => (mode === 'live' ? api.patients() : loadMockPatients())
    .then(ps => { setPatients(ps); setError(null) })
    .catch(e => setError(`Не удалось загрузить пациентов: ${(e as Error).message}`)), [mode])

  useEffect(() => { load() }, [load])

  const refresh = useCallback(async (pid: string) => {
    const b = await api.patient(pid)
    setPatients(ps => ps && (ps.some(p => p.record.patient_id === pid)
      ? ps.map(p => p.record.patient_id === pid ? b : p) : [...ps, b]))
  }, [])

  useEffect(() => {
    if (mode !== 'live') return
    const es = api.stream()
    const onAlert = (ev: MessageEvent) => {
      const a: Alert = JSON.parse(ev.data)
      api.alertAction(a.id, 'ack').catch(() => {})
      setToasts(t => t.some(x => x.id === a.id) ? t : [...t, { id: a.id, pid: a.patient_id, alert: a }])
      beep(a.priority === 'emergency')
      load()
    }
    const onMessage = (ev: MessageEvent) => {
      const m: Message = JSON.parse(ev.data)
      setToasts(t => [...t, { id: `m${m.id}`, pid: m.patient_id, message: m }])
      setMsgTick(x => x + 1)
    }
    es.addEventListener('alert', onAlert as EventListener)
    es.addEventListener('alert_update', () => load())
    es.addEventListener('message', onMessage as EventListener)
    return () => es.close()
  }, [mode, load])

  const decide = async (pid: string, f: Finding, action: Decision['action'], comment?: string) => {
    if (mode === 'live') {
      await api.decide(pid, f.rule_id, action, comment)
      await refresh(pid)
    } else {
      const d: Decision = { patient_id: pid, finding_rule_id: f.rule_id, action, comment, at: new Date().toISOString() }
      setPatients(ps => ps && ps.map(p => p.record.patient_id === pid ? { ...p, decisions: [...(p.decisions ?? []), d] } : p))
    }
  }

  const alertAction = async (pid: string, alertId: string, action: 'accept') => {
    await api.alertAction(alertId, action)
    await refresh(pid)
  }

  const nameOf = (pid: string) => shortName(patients?.find(p => p.record.patient_id === pid)?.record.name ?? pid)
  const dismiss = (id: string) => setToasts(t => t.filter(x => x.id !== id))

  if (error) return <p style={{ padding: 24 }} className="warn-line">{error}</p>
  if (!patients) return <p style={{ padding: 24 }} className="muted">Загружаем пациентов…</p>

  return (
    <>
      <DoctorView patients={patients} mode={mode} user={user} selected={selected} onSelect={setSelected}
        onDecide={decide} onAlertAction={alertAction} msgTick={msgTick} />
      <div className="toasts" aria-live="assertive">
        {toasts.map(t => (
          <div key={t.id} role="alert" className={`toast ${t.alert ? `p-${t.alert.priority}` : 'p-message'}`}
            onClick={() => { setSelected(t.pid); dismiss(t.id) }}>
            {t.alert ? (
              <>
                <span className="toast-head"><b>{PRIORITY_LABEL[t.alert.priority]}</b> · {t.alert.patient_name}</span>
                <span className="toast-text">{t.alert.title}</span>
                {t.alert.escalation_level > 0 && <span className="toast-note">замещение: лечащий врач не принял сигнал вовремя</span>}
              </>
            ) : (
              <>
                <span className="toast-head"><b>Сообщение</b> · {nameOf(t.pid)}</span>
                <span className="toast-text">{t.message!.text}</span>
              </>
            )}
            <button className="toast-close" aria-label="Скрыть" onClick={e => { e.stopPropagation(); dismiss(t.id) }}>×</button>
          </div>
        ))}
      </div>
    </>
  )
}
