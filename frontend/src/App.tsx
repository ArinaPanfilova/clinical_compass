import { useCallback, useEffect, useState } from 'react'
import { api, detectMode, hasToken, loadMockPatients, setToken, type Mode } from './api'
import { AnalyticsView, type AnalyticsQuery, type AviandrReport } from './components/AnalyticsView'
import { DoctorWorkspace } from './components/DoctorWorkspace'
import { Login } from './components/Login'
import { Logo } from './components/Logo'
import { PatientApp } from './components/PatientApp'
import { PhoneSkeleton } from './components/Skeleton'
import { ThemeToggle } from './components/ThemeToggle'
import type { PatientBundle, User } from './types'

const ROLE_LABEL: Record<User['role'], string> = { doctor: 'врач', patient: 'пациент', researcher: 'исследователь' }

/** «Иванова Елена Андреевна, терапевт» → «Иванова Е. А.», подпись «терапевт», инициалы «ИЕ». */
function person(u: User) {
  const [name, spec] = u.display_name.split(',').map(s => s.trim())
  const w = name.split(/\s+/).filter(Boolean)
  const short = w.length === 3 ? `${w[0]} ${w[1][0]}. ${w[2][0]}.` : name
  const initials = (w.length > 1 ? w[0][0] + w[1][0] : name.slice(0, 2)).toUpperCase()
  return { short, sub: spec || ROLE_LABEL[u.role], initials }
}

const ICON = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const

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

  if (!mode) return (
    <div className="boot" aria-busy="true">
      <Logo />
      <span className="boot-bar" aria-hidden />
      <span className="sr-only">Подключаемся к серверу…</span>
    </div>
  )
  if (!user) return <Login mode={mode} onLogin={setUser} />
  return <Shell mode={mode} user={user} onLogout={() => { setToken(null); setUser(null) }} />
}

function Shell({ mode, user, onLogout }: { mode: Mode; user: User; onLogout: () => void }) {
  const [tab, setTab] = useState<'patients' | 'aviandr'>('patients')
  const [generation, setGeneration] = useState(0)    // сброс демо перезагружает данные экранов
  const me = person(user)

  const reset = async () => { await api.reset(); setGeneration(g => g + 1) }

  return (
    <>
      <header className="topbar">
        <Logo />
        {user.role === 'doctor' && (
          <nav className="tabs" aria-label="Раздел">
            <button aria-pressed={tab === 'patients'} onClick={() => setTab('patients')}>
              <svg {...ICON}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5" /><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14.8c1.7.8 2.7 2.5 3 5.2" /></svg>
              <span className="tab-lbl">Пациенты</span>
            </button>
            <button aria-pressed={tab === 'aviandr'} onClick={() => setTab('aviandr')}>
              <svg {...ICON}><path d="M3 20h18" /><path d="M5 16l4.5-5 3.5 3 6-7" /><circle cx="19" cy="7" r="1.2" /></svg>
              <span className="tab-lbl">Наблюдение препарата</span>
            </button>
          </nav>
        )}
        <div className="topbar-end">
          <span className={`conn ${mode}`} title={mode === 'live' ? 'Сервер подключён' : 'Демо без сервера: правила не пересчитываются'}>
            <span className={`dot ${mode === 'live' ? 'live' : ''}`} aria-hidden />
            <span className="conn-text">{mode === 'live' ? 'Сервер подключён' : 'Демо без сервера'}</span>
          </span>
          {mode === 'live' && (
            <button className="btn quiet icon-btn" onClick={reset} aria-label="Сбросить демо" title="Сбросить демо-данные">
              <svg {...ICON}><path d="M4 12a8 8 0 1 0 2.4-5.7" /><path d="M4 4v4.5h4.5" /></svg>
              <span className="lbl">Сбросить демо</span>
            </button>
          )}
          <ThemeToggle />
          <span className="user-chip" title={`${user.display_name} · ${ROLE_LABEL[user.role]}`}>
            <span className={`user-av role-${user.role}`} aria-hidden>{me.initials}</span>
            <span className="user-text"><b>{me.short}</b><small>{me.sub}</small></span>
          </span>
          <button className="btn quiet icon-btn" onClick={onLogout} aria-label="Выйти" title="Выйти">
            <svg {...ICON}><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" /><path d="M10 8l-4 4 4 4M6 12h10" /></svg>
            <span className="lbl">Выйти</span>
          </button>
        </div>
      </header>

      <div key={generation} className="shell-body">
        {user.role === 'doctor' && (
          <>
            {/* Рабочее место не размонтируется: поток алертов работает и на вкладке аналитики */}
            <div className="fade-in" hidden={tab !== 'patients'}><DoctorWorkspace user={user} mode={mode} /></div>
            {tab === 'aviandr' && <div className="fade-in"><AnalyticsSlot role="doctor" mode={mode} /></div>}
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
  return (
    <div className="patient-wrap">
      {b ? <PatientApp b={b} mode={mode} onSubmitted={load} /> : <PhoneSkeleton />}
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
