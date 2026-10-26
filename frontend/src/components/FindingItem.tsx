import { useEffect, useState } from 'react'
import type { Alert, Decision, Finding } from '../types'

const ROUTING_BADGE = {
  mandatory: <span className="badge must"><svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><circle cx="5" cy="5" r="4" fill="currentColor" /></svg>Обязательно к психиатру</span>,
  desirable: <span className="badge want"><svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><circle cx="5" cy="5" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>Желательно к психиатру</span>,
}

const LIFECYCLE = ['создан', 'доставлен', 'принят врачом', 'действие', 'закрыт'] as const

interface Props {
  f: Finding
  decision?: Decision
  onDecide: (action: Decision['action'], comment?: string) => Promise<void> | void
  alert?: Alert                                   // алерт на сервере: статус и метки времени
  onAccept?: (alertId: string) => Promise<void> | void
}

const STAGE: Record<Alert['status'], number> = { created: 1, delivered: 2, accepted: 3, closed: 5 }

export function FindingItem({ f, decision, onDecide, alert, onAccept }: Props) {
  const [mode, setMode] = useState<null | 'reject' | 'modify'>(null)
  const [comment, setComment] = useState('')
  const [now, setNow] = useState(Date.now())
  const [accepted, setAccepted] = useState(false)
  const isAlert = f.kind === 'alert'

  useEffect(() => {
    if (!isAlert || decision) return
    const t = setInterval(() => setNow(Date.now()), 15_000)
    return () => clearInterval(t)
  }, [isAlert, decision])

  const cls = ['finding', `p-${f.priority}`, `k-${f.kind}`, f.routing ? `r-${f.routing}` : '', decision ? 'decided' : ''].join(' ')
  const createdAt = alert ? Date.parse(alert.created_at) : null
  const minutes = createdAt ? Math.max(0, Math.round((now - createdAt) / 60_000)) : null
  // Без сервера: создан и доставлен — сразу, дальше ждём врача
  const stage = decision ? 5 : alert ? STAGE[alert.status] : accepted ? 3 : 2
  const canAccept = isAlert && (alert ? alert.status === 'created' || alert.status === 'delivered' : !accepted)
  const accept = () => alert && onAccept ? onAccept(alert.id) : setAccepted(true)

  return (
    <article className={cls} aria-label={f.title}>
      <div className="tags">
        {f.priority === 'emergency' && <span className="badge emerg">Экстренно</span>}
        {f.kind === 'alert' && f.priority === 'urgent' && <span className="badge urgent">Срочно</span>}
        {f.kind === 'therapy_warning' && <span className="badge rx">Безопасность терапии</span>}
        {f.kind === 'data_quality' && <span className="badge dq">Качество данных</span>}
        {f.routing && ROUTING_BADGE[f.routing]}
      </div>
      <h3 className="f-title">{f.title}</h3>
      <p className="msg">{f.message}</p>

      {isAlert && (
        <ol className="lifecycle" aria-label="Статус алерта">
          {LIFECYCLE.map((s, i) => (
            <li key={s} className={i < stage ? 'done' : i === stage && !decision ? 'now' : ''}>{s}</li>
          ))}
          {minutes !== null && !decision && <li className="timer">{minutes < 1 ? 'только что' : `${minutes} мин назад`}</li>}
        </ol>
      )}
      {alert && alert.escalation_level > 0 && (
        <p className="warn-line">Передан заместителю: лечащий врач не принял сигнал за отведённое время.</p>
      )}

      <details>
        <summary>Основание</summary>
        <ul>
          {f.sources.map(s => <li key={s}>{s}</li>)}
          <li>Данные: {Object.entries(f.evidence).map(([k, v]) => `${k} = ${v ?? 'нет данных'}`).join('; ')}</li>
          <li>Правило {f.rule_id} v{f.rule_version}{f.rule_status === 'draft' ? ' — черновик, ждёт утверждения клиническим лидом' : ''}</li>
          {f.auto_actions.length > 0 && <li>Система уже сделала: {f.auto_actions.map(a => AUTO[a] ?? a).join(', ')}</li>}
        </ul>
      </details>

      <div className="actions">
        {decision ? (
          <p className="decided-note">
            {ACTION_LABEL[decision.action]} {new Date(decision.at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}
            {decision.comment ? `: ${decision.comment}` : ''}
          </p>
        ) : mode ? (
          <div className="reason">
            <label htmlFor={`r-${f.rule_id}`} className="faint">
              {mode === 'reject' ? 'Почему отклоняете' : 'Что меняете'}
            </label>
            <textarea id={`r-${f.rule_id}`} value={comment} onChange={e => setComment(e.target.value)} autoFocus />
            <button className="btn primary" disabled={!comment.trim()} onClick={() => onDecide(mode, comment.trim())}>
              {mode === 'reject' ? 'Отклонить' : 'Сохранить'}
            </button>
            <button className="btn quiet" onClick={() => setMode(null)}>Отмена</button>
          </div>
        ) : (
          <>
            {canAccept && <button className="btn danger" onClick={accept}>Принять в работу</button>}
            <button className="btn primary" onClick={() => onDecide('confirm')}>Подтвердить</button>
            <div className="secondary">
              <button className="btn quiet" onClick={() => setMode('modify')}>Изменить</button>
              <button className="btn quiet" onClick={() => setMode('reject')}>Отклонить</button>
            </div>
          </>
        )}
      </div>
    </article>
  )
}

const ACTION_LABEL: Record<string, string> = {
  confirm: 'Подтверждено врачом', reject: 'Отклонено врачом', modify: 'Изменено врачом',
}

const AUTO: Record<string, string> = {
  notify_doctor: 'уведомила врача',
  notify_deputy_on_timeout: 'передаст замещающему врачу при просрочке',
  show_patient_emergency_instructions: 'показала пациенту экстренную инструкцию',
  create_review_task: 'создала задачу пересмотра',
  request_repeat_questionnaire: 'запросила повторную анкету',
  start_escalation_timer: 'запустила таймер эскалации',
}
