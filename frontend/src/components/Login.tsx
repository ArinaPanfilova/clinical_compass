import { useState, type FormEvent } from 'react'
import { api, setToken, type Mode } from '../api'
import { DEMO_ACCOUNTS } from '../content'
import type { User } from '../types'
import { Logo } from './Logo'

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
    <div className="login-wrap">
      <main className="login-card">
        <Logo />
        <h1>Вход в Компас</h1>
        <p className="muted">Ассистент врача для ведения взрослых пациентов с тревожной и депрессивной симптоматикой.
          Клинические решения принимает только врач.</p>

        <form className="login-form" onSubmit={submit}>
          <label>Логин<input className="field" autoComplete="username" value={login} onChange={e => setLogin(e.target.value)} /></label>
          <label>Пароль<input className="field" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
          <button className="btn primary" disabled={busy || !login.trim() || !password}>Войти</button>
        </form>
        {err && <p className="warn-line must" role="alert">{err}</p>}

        <div className="demo-head">
          <h2>Демо-аккаунты</h2>
          <span className="faint">пароль у всех — demo · данные синтетические</span>
        </div>
        <div className="demo-grid">
          {DEMO_ACCOUNTS.map(a => (
            <button key={a.login} className={`demo-acc role-${a.role}`} disabled={busy} onClick={() => enter(a.login, 'demo')}>
              <b>{a.name}</b>
              <span>{a.note}</span>
            </button>
          ))}
        </div>
        {mode === 'demo' && <p className="faint">Сервер не подключён: открываются демо-данные, правила не пересчитываются, алерты и сообщения недоступны.</p>}
      </main>
    </div>
  )
}
