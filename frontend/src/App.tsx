import { useEffect, useState } from 'react'
import { loadPatients, resetDemo, type Mode } from './api'
import { DoctorView, shortName } from './components/DoctorView'
import { PatientApp } from './components/PatientApp'
import type { Decision, PatientBundle } from './types'

export default function App() {
  const [view, setView] = useState<'doctor' | 'patient'>('doctor')
  const [mode, setMode] = useState<Mode>('demo')
  const [patients, setPatients] = useState<PatientBundle[] | null>(null)
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [alertTimes, setAlertTimes] = useState<Record<string, number>>({})
  const [pid, setPid] = useState('P-001')
  const [error, setError] = useState<string | null>(null)

  const load = () => loadPatients()
    .then(({ mode, patients }) => {
      setMode(mode); setPatients(patients)
      const t: Record<string, number> = {}
      for (const p of patients) for (const f of p.evaluation.findings)
        if (f.kind === 'alert') t[`${p.record.patient_id}:${f.rule_id}`] = Date.now() - 4 * 60_000
      setAlertTimes(prev => ({ ...t, ...prev }))
    })
    .catch(() => setError('Не удалось загрузить данные пациентов. Запустите сервер правил или пересоберите демо-данные.'))

  useEffect(() => { load() }, [])

  const onSubmitted = (id: string, ev: PatientBundle['evaluation']) => {
    setPatients(ps => ps && ps.map(p => p.record.patient_id === id ? { ...p, evaluation: ev } : p))
    const now = Date.now()
    setAlertTimes(prev => {
      const next = { ...prev }
      for (const f of ev.findings) if (f.kind === 'alert' && !next[`${id}:${f.rule_id}`]) next[`${id}:${f.rule_id}`] = now
      return next
    })
    // В live-режиме подтягиваем полную запись (дневник, анкеты) с сервера
    if (mode === 'live') loadPatients().then(r => setPatients(r.patients))
  }

  if (error) return <p style={{ padding: 24 }}>{error}</p>
  if (!patients) return <p style={{ padding: 24 }} className="muted">Загружаем пациентов…</p>
  const current = patients.find(p => p.record.patient_id === pid) ?? patients[0]

  return (
    <>
      <header className="topbar">
        <span className="logo">
          <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M12 5l3 7-3 7-3-7z" fill="currentColor" /></svg>
          Компас
        </span>
        <div className="seg" role="group" aria-label="Кабинет">
          <button aria-pressed={view === 'doctor'} onClick={() => setView('doctor')}>Врач</button>
          <button aria-pressed={view === 'patient'} onClick={() => setView('patient')}>Пациент</button>
        </div>
        {view === 'patient' && (
          <select className="select" aria-label="Пациент" value={current.record.patient_id} onChange={e => setPid(e.target.value)}>
            {patients.map(p => <option key={p.record.patient_id} value={p.record.patient_id}>{shortName(p.record.name)}</option>)}
          </select>
        )}
        <span className="mode">
          <span className={`dot ${mode === 'live' ? 'live' : ''}`} />
          {mode === 'live' ? 'Сервер правил подключён' : 'Демо-данные без сервера'}
          {mode === 'live' && <button className="btn quiet" onClick={async () => { await resetDemo(); setDecisions([]); setAlertTimes({}); load() }}>Сбросить демо</button>}
        </span>
      </header>

      {view === 'doctor' ? (
        <DoctorView patients={patients} mode={mode} decisions={decisions}
          onDecision={d => setDecisions(ds => [...ds, d])} alertTimes={alertTimes} />
      ) : (
        <div className="patient-wrap">
          <PatientApp key={current.record.patient_id} b={current} mode={mode} onSubmitted={onSubmitted} />
          <aside className="side-notes">
            <h2>Как это работает</h2>
            <ul>
              <li>Ответы попадают в карточку лечащего врача без посредников.</li>
              <li>Ответ на вопрос 9 больше нуля создаёт срочный алерт врачу независимо от суммы баллов.</li>
              <li>Кнопка «Мне сейчас очень плохо» сразу показывает экстренную инструкцию и уведомляет врача; инструкция не ждёт ответа сервера.</li>
              <li>Пропущенный вопрос не превращается в ноль: пропуск вопроса 9 — отдельный сигнал врачу.</li>
            </ul>
            <p className="faint">Тексты вопросов — рабочий перевод; перед апробацией заменяются валидированной русской версией.</p>
          </aside>
        </div>
      )}
    </>
  )
}
