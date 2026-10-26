import { useCallback, useEffect, useState } from 'react'
import { api, detectMode, hasToken, loadMockPatients, setToken, type Mode } from './api'
import { AnalyticsView, type AnalyticsQuery, type AviandrReport } from './components/AnalyticsView'
import { DoctorWorkspace } from './components/DoctorWorkspace'
import { Login } from './components/Login'
import { Logo } from './components/Logo'
import { PatientApp } from './components/PatientApp'
import type { PatientBundle, User } from './types'

const ROLE_LABEL: Record<User['role'], string> = { doctor: 'врач', patient: 'пациент', researcher: 'исследователь' }

export default function App() {
  const [mode, setMode] = useState<Mode | null>(null)
  const [user, setUser] = useState<User | null>(null)

  useEffect(() => {
    detectMode().then(async m => {
      if (m === 'live' && hasToken()) {
        try { setUser(await api.me()) } catch { setToken(null) }
      }
      setMode(m)
    })
  }, [])

  if (!mode) return <p style={{ padding: 24 }} className="muted">Подключаемся к серверу…</p>
  if (!user) return <Login mode={mode} onLogin={setUser} />
  return <Shell mode={mode} user={user} onLogout={() => { setToken(null); setUser(null) }} />
}

function Shell({ mode, user, onLogout }: { mode: Mode; user: User; onLogout: () => void }) {
  const [tab, setTab] = useState<'patients' | 'aviandr'>('patients')
  const [generation, setGeneration] = useState(0)    // сброс демо перезагружает данные экранов

  const reset = async () => { await api.reset(); setGeneration(g => g + 1) }

  return (
    <>
      <header className="topbar">
        <Logo />
        {user.role === 'doctor' && (
          <div className="seg" role="group" aria-label="Раздел">
            <button aria-pressed={tab === 'patients'} onClick={() => setTab('patients')}>Пациенты</button>
            <button aria-pressed={tab === 'aviandr'} onClick={() => setTab('aviandr')}>Авиандр</button>
          </div>
        )}
        <span className="mode">
          <span className={`dot ${mode === 'live' ? 'live' : ''}`} />
          {mode === 'live' ? 'Сервер подключён' : 'Демо без сервера'}
          {mode === 'live' && <button className="btn quiet" onClick={reset}>Сбросить демо</button>}
          <span className="whoami">{user.display_name} · {ROLE_LABEL[user.role]}</span>
          <button className="btn quiet" onClick={onLogout}>Выйти</button>
        </span>
      </header>

      <div key={generation}>
        {user.role === 'doctor' && (
          <>
            {/* Рабочее место не размонтируется: поток алертов работает и на вкладке аналитики */}
            <div hidden={tab !== 'patients'}><DoctorWorkspace user={user} mode={mode} /></div>
            {tab === 'aviandr' && <AnalyticsSlot role="doctor" mode={mode} />}
          </>
        )}
        {user.role === 'researcher' && <AnalyticsSlot role="researcher" mode={mode} />}
        {user.role === 'patient' && user.patient_id && <PatientHome pid={user.patient_id} mode={mode} />}
      </div>
    </>
  )
}

function PatientHome({ pid, mode }: { pid: string; mode: Mode }) {
  const [b, setB] = useState<PatientBundle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => (mode === 'live' ? api.patient(pid)
    : loadMockPatients().then(ps => ps.find(p => p.record.patient_id === pid)!))
    .then(setB).catch(e => setError((e as Error).message)), [pid, mode])
  useEffect(() => { load() }, [load])

  if (error) return <p style={{ padding: 24 }} className="warn-line">Не удалось загрузить данные: {error}</p>
  if (!b) return <p style={{ padding: 24 }} className="muted">Загружаем…</p>
  return (
    <div className="patient-wrap">
      <PatientApp b={b} mode={mode} onSubmitted={load} />
      <aside className="side-notes">
        <h2>Как это работает</h2>
        <ul>
          <li>Ответы попадают в карточку лечащего врача без посредников.</li>
          <li>Ответ на вопрос 9 больше нуля создаёт срочный сигнал врачу независимо от суммы баллов. Если врач не принял его вовремя, сигнал уходит заместителю.</li>
          <li>Кнопка «Мне сейчас очень плохо» сразу показывает экстренную инструкцию и уведомляет врача; инструкция не ждёт ответа сервера.</li>
          <li>Пропущенный вопрос не превращается в ноль: пропуск вопроса 9 — отдельный сигнал врачу.</li>
        </ul>
        <p className="faint">Тексты вопросов — рабочий перевод; перед апробацией заменяются валидированной русской версией.</p>
      </aside>
    </div>
  )
}

// Без сервера — заранее выгруженный отчёт (фильтры не пересчитываются)
function AnalyticsSlot({ role, mode }: { role: 'doctor' | 'researcher'; mode: Mode }) {
  const fetchReport = (q: AnalyticsQuery) => mode === 'live'
    ? api.analytics<AviandrReport>({ ...q })
    : fetch(`./mock/analytics-${role}.json`).then(r => r.json() as Promise<AviandrReport>)
  return <AnalyticsView role={role} fetchReport={fetchReport} />
}
