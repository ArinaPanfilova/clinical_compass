import { useState } from 'react'
import { api, newKey } from '../api'
import type { Consent } from '../types'
import { Logo } from './Logo'

// Согласие пациента на обработку данных о здоровье. До согласия данные не принимаются,
// но экстренная кнопка работает: защита жизни и здоровья — отдельное основание (152-ФЗ, ст. 10).

export function ConsentScreen({ consent, pid, onAccepted, onLogout }:
  { consent: Consent; pid: string; onAccepted: () => void; onLogout: () => void }) {
  const [agree, setAgree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [sos, setSos] = useState(false)

  const accept = async () => {
    setBusy(true); setErr(null)
    try { await api.acceptConsent(consent.version); onAccepted() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const emergency = () => {
    setSos(true)
    api.selfReport(pid, { questionnaires: [], emergency: true }, newKey()).catch(() => {})
  }

  return (
    <div className="login-wrap">
      <main className="login-card consent-card">
        <Logo />
        <h1>{consent.title}</h1>
        <ul className="consent-points">{consent.points.map(p => <li key={p}>{p}</li>)}</ul>
        <p className="faint">Основание: {consent.basis}. Версия текста от {new Date(consent.version).toLocaleDateString('ru-RU')}.</p>
        <label className="consent-check">
          <input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} />
          Я прочитал(а) и согласен(на) на обработку моих данных о здоровье лечащим врачом
        </label>
        {err && <p className="warn-line must">{err}</p>}
        <div className="doc-actions">
          <button className="btn primary" disabled={!agree || busy} onClick={accept}>Принимаю</button>
          <button className="btn quiet" onClick={onLogout}>Выйти</button>
        </div>
        <button className="sos-inline" onClick={emergency}>Мне сейчас очень плохо</button>
        {sos && (
          <p className="warn-line must" role="alert">Если вы в опасности прямо сейчас — звоните 112. Врач получил уведомление,
            но приложение не ведёт круглосуточное наблюдение.</p>
        )}
      </main>
    </div>
  )
}
