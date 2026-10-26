import { useState } from 'react'
import { api } from '../api'
import { NECESSITY_LABEL, REFERRAL_STATUS, URGENCY_LABEL } from '../content'
import type { PatientBundle, Referral } from '../types'

// Направление к психиатру оформляет врач. Система подсказывает необходимость и срочность
// по сработавшему правилу маршрутизации; врач может изменить их и обязан указать основание.

const date = (s: string) => new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })

export function ReferralPanel({ b, onReplace }: { b: PatientBundle; onReplace: (b: PatientBundle) => void }) {
  const pid = b.record.patient_id
  const refs = b.referrals ?? []
  const routing = b.evaluation.findings.filter(f => f.routing)
  const top = routing.find(f => f.routing === 'mandatory') ?? routing[0]
  const [open, setOpen] = useState(false)
  const [necessity, setNecessity] = useState<Referral['necessity']>(top?.routing ?? 'desirable')
  const [urgency, setUrgency] = useState<Referral['urgency']>(
    top?.priority === 'emergency' ? 'emergency' : top?.priority === 'urgent' ? 'urgent' : 'planned')
  const [reason, setReason] = useState(top ? top.title : '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null)
    try { await fn(); onReplace(await api.patient(pid)) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const issue = () => run(async () => {
    await api.issueReferral(pid, { necessity, urgency, reason: reason.trim(), rule_id: top?.rule_id ?? null })
    setOpen(false)
  })

  return (
    <div className="referral">
      {refs.length === 0 && !open && (
        <p className="empty">{top ? `Система предлагает: ${NECESSITY_LABEL[top.routing!].toLowerCase()} к психиатру (${top.rule_id}). Решение — за вами.` : 'Сигналов маршрутизации нет.'}</p>
      )}
      {refs.map(r => (
        <div key={r.id} className={`ref-item ${r.necessity}`}>
          <span className={`badge ${r.necessity === 'mandatory' ? 'must' : 'want'}`}>{NECESSITY_LABEL[r.necessity]} к психиатру · {URGENCY_LABEL[r.urgency]}</span>
          <p>{r.reason}</p>
          <span className="faint">оформлено {date(r.created_at)} · {REFERRAL_STATUS[r.status]}{r.note ? ` · ${r.note}` : ''}</span>
          {(r.status === 'issued' || r.status === 'scheduled') && (
            <div className="ref-actions">
              {r.status === 'issued' && <button className="mini" disabled={busy} onClick={() => run(() => api.referralStatus(r.id, 'scheduled'))}>Пациент записан</button>}
              <button className="mini" disabled={busy} onClick={() => run(() => api.referralStatus(r.id, 'completed'))}>Консультация состоялась</button>
              <button className="mini" disabled={busy} onClick={() => run(() => api.referralStatus(r.id, 'cancelled'))}>Отменить</button>
            </div>
          )}
        </div>
      ))}
      {open ? (
        <div className="ref-form">
          <fieldset className="ref-choice">
            <legend className="faint">Необходимость</legend>
            {(['mandatory', 'desirable'] as const).map(v => (
              <label key={v}><input type="radio" name={`nec-${pid}`} checked={necessity === v} onChange={() => setNecessity(v)} /> {NECESSITY_LABEL[v]}</label>
            ))}
          </fieldset>
          <fieldset className="ref-choice">
            <legend className="faint">Срочность</legend>
            {(['emergency', 'urgent', 'planned'] as const).map(v => (
              <label key={v}><input type="radio" name={`urg-${pid}`} checked={urgency === v} onChange={() => setUrgency(v)} /> {URGENCY_LABEL[v]}</label>
            ))}
          </fieldset>
          <label className="faint" htmlFor={`ref-${pid}`}>Основание направления</label>
          <textarea id={`ref-${pid}`} className="field" value={reason} onChange={e => setReason(e.target.value)} />
          {err && <p className="warn-line">{err}</p>}
          <div className="ref-actions">
            <button className="btn primary" disabled={busy || !reason.trim()} onClick={issue}>Оформить направление</button>
            <button className="btn quiet" onClick={() => setOpen(false)}>Отмена</button>
          </div>
        </div>
      ) : (
        <button className="btn" onClick={() => setOpen(true)}>Направить к психиатру</button>
      )}
    </div>
  )
}

export function PatientReferrals({ referrals }: { referrals: Referral[] }) {
  const active = referrals.filter(r => r.status === 'issued' || r.status === 'scheduled')
  if (!active.length) return null
  return (
    <>
      {active.map(r => (
        <div key={r.id} className={`task ref-patient ${r.necessity}`} role="note">
          <h3>Врач рекомендовал консультацию психиатра</h3>
          <p>{NECESSITY_LABEL[r.necessity]}, {URGENCY_LABEL[r.urgency]}. {r.status === 'scheduled' ? 'Вы записаны на приём.' : 'Запишитесь на приём — врач подскажет, как.'}</p>
          <p className="faint">Это не диагноз: консультация нужна, чтобы подобрать помощь точнее.</p>
        </div>
      ))}
    </>
  )
}
