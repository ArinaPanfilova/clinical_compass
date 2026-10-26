import { useState, type FormEvent } from 'react'
import { api, setToken, type Mode } from '../api'
import { DEMO_ACCOUNTS } from '../content'
import type { User } from '../types'
import { Logo } from './Logo'
import { ThemeToggle } from './ThemeToggle'

const ROLE_GROUPS: { role: User['role']; title: string }[] = [
  { role: 'doctor', title: 'Врачи' },
  { role: 'patient', title: 'Пациенты' },
  { role: 'researcher', title: 'Исследование' },
]

const initials = (n: string) => n.replace(/[.]/g, '').split(/\s+/).map(w => w[0]).join('').slice(0, 2)

export function Login({ mode, onLogin }: { mode: Mode; onLogin: (u: User) => void }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const enter = async (l: string, p: string) => {
    setErr(null); setBusy(true)
    try {
      if (mode === 'live') {
        const r = await api.login(l, p)
        setToken(r.token)
        onLogin(r.user)
      } else {
        const a = DEMO_ACCOUNTS.find(x => x.login === l)
        if (!a) throw new Error('Сервер не подключён: доступны только демо-аккаунты')
        onLogin({ id: a.id, role: a.role, display_name: a.name, patient_id: a.patient_id })
      }
    } catch (e) {
      setErr((e as Error).message)
    } finally { setBusy(false) }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); enter(login.trim(), password) }

  return (
    <div className="login">
      <div className="login-tools"><ThemeToggle /></div>
      <aside className="login-hero">
        <Logo />
        <div className="hero-copy">
          <p className="hero-kicker">Цифровой ассистент врача</p>
          <p className="hero-title">Пациенты с тревогой и депрессией остаются под наблюдением и между приёмами</p>
          <ul className="hero-points">
            <li><b>Сигнал о риске</b> приходит врачу сразу. Если врач не принял его вовремя, сигнал уходит заместителю.</li>
            <li><b>Каждая подсказка</b> показывает основание и источник. Решение принимает врач.</li>
            <li><b>PHQ-9, GAD-7</b>, дневник, отметки приёма и профиль безопасности собраны в одной карточке.</li>
          </ul>
        </div>
        <CompassArt />
        <p className="hero-foot">Прототип · все данные синтетические</p>
      </aside>

      <main className="login-main">
        <div className="login-card">
          <h1>Вход в Компас</h1>
          <p className="muted">Помогает врачу вести взрослых пациентов с тревогой и депрессией.
            Клинические решения принимает только врач.</p>

          <form className="login-form" onSubmit={submit}>
            <label>Логин<input className="field" autoComplete="username" value={login} onChange={e => setLogin(e.target.value)} /></label>
            <label>Пароль<input className="field" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
            <button className="btn primary" disabled={busy || !login.trim() || !password}>Войти</button>
          </form>
          {err && <p className="warn-line must" role="alert">{err}</p>}

          <div className="demo-head">
            <h2>Демо-аккаунты</h2>
            <span className="faint">пароль у всех: demo · данные синтетические</span>
          </div>
          {ROLE_GROUPS.map(g => (
            <section key={g.role} className="demo-group" aria-label={g.title}>
              <h3 className="eyebrow">{g.title}</h3>
              <div className="demo-grid">
                {DEMO_ACCOUNTS.filter(a => a.role === g.role).map(a => (
                  <button key={a.login} className={`demo-acc role-${a.role}`} disabled={busy} onClick={() => enter(a.login, 'demo')}>
                    <span className="demo-av" aria-hidden>{initials(a.name)}</span>
                    <span className="demo-text">
                      <b>{a.name}</b>
                      <span>{a.note}</span>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          ))}
          {mode === 'demo' && <p className="faint">Сервер не подключён. Открыты демо-данные: правила не пересчитываются, алерты и сообщения не работают.</p>}
        </div>
      </main>
    </div>
  )
}

/** Шкала компаса: деления, румбы по-русски и стрелка, которая один раз «успокаивается» при входе. */
function CompassArt() {
  const ticks = Array.from({ length: 72 }, (_, i) => i * 5)
  return (
    <svg className="compass-art" viewBox="-200 -200 400 400" aria-hidden>
      <circle r="188" className="ca-ring" />
      <circle r="150" className="ca-ring thin" />
      <circle r="96" className="ca-ring thin" />
      {ticks.map(a => (
        <line key={a} className={a % 45 === 0 ? 'ca-tick major' : 'ca-tick'} y1={-188} y2={a % 45 === 0 ? -166 : a % 15 === 0 ? -174 : -180}
          transform={`rotate(${a})`} />
      ))}
      {[['С', 0], ['В', 90], ['Ю', 180], ['З', 270]].map(([t, a]) => (
        <text key={t} className="ca-letter" transform={`rotate(${a}) translate(0 -128) rotate(${-Number(a)})`} textAnchor="middle" dominantBaseline="central">{t}</text>
      ))}
      <g className="ca-needle">
        <path d="M0 -112 L16 0 L-16 0 Z" className="ca-north" />
        <path d="M-16 0 L16 0 L0 112 Z" className="ca-south" />
        <circle r="6" className="ca-hub" />
      </g>
    </svg>
  )
}
