import { useRef, useState } from 'react'
import { api, newKey, type Mode, type SelfReportBody } from '../api'
import { GAD7, OPTIONS, PHQ9 } from '../content'
import type { PatientBundle } from '../types'
import { MessagesPanel } from './MessagesPanel'
import { TrendChart } from './TrendChart'

interface Props {
  b: PatientBundle
  mode: Mode
  onSubmitted: () => void
}

type Tab = 'today' | 'dynamics' | 'messages'

export function PatientApp({ b, mode, onSubmitted }: Props) {
  const [tab, setTab] = useState<Tab>('today')
  const [sos, setSos] = useState(false)
  const [quiz, setQuiz] = useState(false)
  const [answers, setAnswers] = useState<{ phq9: (number | null)[]; gad7: (number | null)[] } | null>(null)
  const [med, setMed] = useState<'taken' | 'missed' | null>(null)
  const [medNote, setMedNote] = useState<string | null>(null)
  // Один ключ на одну отправку: повтор после обрыва связи не задвоит самоотчёт и алерт
  const keyRef = useRef<string | null>(null)
  const [diary, setDiary] = useState('')
  const [ae, setAe] = useState('')
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const firstName = b.record.name.split(' ')[0]
  const onTherapy = b.record.therapy.current.length > 0
  // Окно анкеты — 2 недели: чаще выдавать нельзя без потери смысла шкалы
  const phq = b.evaluation.details.scales.phq9 ?? []
  const lastDate = phq.length ? new Date(phq[phq.length - 1].date) : null
  const now = new Date()
  const todayUtc = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())   // календарные дни по местной дате
  const daysSince = lastDate ? Math.round((todayUtc - +lastDate) / 86_400_000) : 99
  const due = daysSince >= 14

  const send = async () => {
    const body: SelfReportBody = {
      questionnaires: answers ? [{ scale: 'phq9', answers: answers.phq9 }, { scale: 'gad7', answers: answers.gad7 }] : [],
      diary_text: diary.trim() || undefined,
      adverse_event: ae.trim() || undefined,
    }
    setBusy(true)
    try {
      if (mode === 'live') {
        keyRef.current ??= newKey()
        const r = await api.selfReport(b.record.patient_id, body, keyRef.current)
        keyRef.current = null
        onSubmitted()
        setResult({ ok: true, text: r.patient_messages[0] ?? 'Отправлено. Врач увидит ответы в вашей карточке.' })
      } else {
        setResult({ ok: true, text: 'Сохранено в демо без сервера: правила пересчитываются только когда сервер подключён.' })
      }
      setAnswers(null); setDiary(''); setAe('')
    } catch (e) {
      setResult({ ok: false, text: `Не отправилось: ${(e as Error).message}. Ответы сохранены на экране — попробуйте ещё раз.` })
    } finally { setBusy(false) }
  }

  const markIntake = async (status: 'taken' | 'missed') => {
    setMed(status)
    if (mode !== 'live') { setMedNote('В демо без сервера отметка не сохраняется.'); return }
    try {
      await api.intake(b.record.patient_id, status)
      setMedNote(status === 'taken' ? 'Отметка сохранена: принято сегодня.' : 'Отметка сохранена. Если пропуски повторяются, обсудите это с врачом — так можно подобрать удобную схему.')
    } catch (e) { setMedNote(`Не сохранилось: ${(e as Error).message}`) }
  }

  const emergency = async () => {
    setSos(true)   // инструкция показывается сразу, не дожидаясь сервера
    if (mode === 'live') {
      try {
        await api.selfReport(b.record.patient_id, { questionnaires: [], emergency: true }, newKey())
        onSubmitted()
      } catch { /* инструкция уже на экране */ }
    }
  }

  return (
    <div className="phone" aria-label="Приложение пациента">
      <div className="phone-status" aria-hidden><span>9:41</span><svg width="26" height="12" viewBox="0 0 26 12"><rect x=".5" y=".5" width="22" height="11" rx="3" fill="none" stroke="currentColor" opacity=".5" /><rect x="2.5" y="2.5" width="16" height="7" rx="1.5" fill="currentColor" /><rect x="23.5" y="4" width="2" height="4" rx="1" fill="currentColor" opacity=".5" /></svg></div>
      <div className="phone-head">
        <p className="faint">{new Date().toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })}</p>
        <h1 style={{ fontSize: 22 }}>{tab === 'today' ? `Здравствуйте, ${firstName}` : tab === 'dynamics' ? 'Моя динамика' : 'Сообщения врачу'}</h1>
      </div>

      <div className="phone-body">
        {quiz ? (
          <Questionnaire onDone={a => { setAnswers(a); setQuiz(false) }} onCancel={() => setQuiz(false)} />
        ) : tab === 'today' ? (
          <>
            {result && <p className={`note-box ${result.ok ? 'msg-ok' : 'msg-alert'}`} role="status">{result.text}</p>}
            <div className={`task ${due && !answers ? 'due' : ''}`}>
              <h3>Анкета за последние 2 недели</h3>
              <p className="muted">
                {due ? '16 вопросов о настроении и тревоге, около 3 минут.' : `Следующая анкета через ${14 - daysSince} дн. Вопросы охватывают две недели, поэтому чаще заполнять не нужно.`}
              </p>
              {answers
                ? <p className="note-box msg-ok">Ответы готовы к отправке.</p>
                : due
                  ? <button className="big-btn" onClick={() => setQuiz(true)}>Заполнить анкету</button>
                  : <button className="btn" style={{ marginTop: 10, width: '100%' }} onClick={() => setQuiz(true)}>Заполнить раньше, если попросил врач</button>}
            </div>
            {onTherapy && (
              <div className="task">
                <h3>Приняли лекарство сегодня?</h3>
                <div className="choice-row">
                  {([['taken', 'Принял(а)'], ['missed', 'Пропустил(а)']] as const).map(([v, l]) => (
                    <button key={v} className="choice" aria-pressed={med === v} onClick={() => markIntake(v)}>{l}</button>
                  ))}
                </div>
                {medNote && <p className="faint" style={{ marginTop: 8 }}>{medNote}</p>}
              </div>
            )}
            <div className="task">
              <h3>Как вы сегодня?</h3>
              <label className="muted" htmlFor="diary">Несколько слов своими словами — врач прочитает</label>
              <textarea id="diary" className="field" value={diary} onChange={e => setDiary(e.target.value)} />
            </div>
            {onTherapy && (
              <div className="task">
                <h3>Что-то беспокоит после начала лечения?</h3>
                <label className="muted" htmlFor="ae">Например, тошнота, сонливость, сыпь</label>
                <textarea id="ae" className="field" style={{ minHeight: 56 }} value={ae} onChange={e => setAe(e.target.value)} />
              </div>
            )}
            <button className="big-btn" disabled={busy || (!answers && !diary.trim() && !ae.trim())} onClick={() => send()}>
              {busy ? 'Отправляем…' : 'Отправить врачу'}
            </button>
            <p className="note-box">Врач читает сообщения по будням с 9 до 18. Приложение не следит за вашим состоянием круглосуточно.</p>
          </>
        ) : tab === 'dynamics' ? (
          <>
            <p className="muted" style={{ marginBottom: 8 }}>Настроение (PHQ-9): чем ниже, тем лучше.</p>
            <div className="mini-chart"><TrendChart compact scale="phq9" points={b.evaluation.details.scales.phq9 ?? []} /></div>
            <p className="muted" style={{ margin: '16px 0 8px' }}>Тревога (GAD-7): чем ниже, тем лучше.</p>
            <div className="mini-chart"><TrendChart compact scale="gad7" points={b.evaluation.details.scales.gad7 ?? []} /></div>
            <p className="note-box">Баллы помогают врачу видеть изменения. Сами по себе они не ставят диагноз; обсудите их на приёме.</p>
          </>
        ) : (
          <>
            <div className="note-box">Сообщения прочитает ваш врач в рабочее время. «Прочитано» не означает, что вопрос решён — врач ответит отдельно. Если вам плохо прямо сейчас — нажмите красную кнопку внизу.</div>
            <MessagesPanel pid={b.record.patient_id} mode={mode} role="patient" />
          </>
        )}
      </div>

      <nav className="phone-tabs" aria-label="Разделы">
        {([['today', 'Сегодня'], ['dynamics', 'Динамика'], ['messages', 'Сообщения']] as const).map(([v, l]) => (
          <button key={v} aria-pressed={tab === v} onClick={() => { setTab(v); setQuiz(false) }}>{l}</button>
        ))}
      </nav>
      <button className="sos" onClick={emergency}>Мне сейчас очень плохо</button>

      {sos && (
        <div className="modal-back" role="dialog" aria-modal="true" aria-labelledby="sos-title">
          <div className="sheet">
            <h2 id="sos-title">Если вы в опасности прямо сейчас</h2>
            <p>Позвоните в экстренную службу. Врач получил уведомление{mode === 'demo' ? ' (в демо — без сервера)' : ''}, но не может приехать или ответить мгновенно.</p>
            <a className="call" href="tel:112">Позвонить 112</a>
            <p className="faint">Контакты служб психологической помощи для вашего региона утверждает клиническая команда (заполнить перед апробацией).</p>
            <button className="btn" style={{ width: '100%', marginTop: 12 }} onClick={() => setSos(false)}>Закрыть</button>
          </div>
        </div>
      )}
    </div>
  )
}

function Questionnaire({ onDone, onCancel }: { onDone: (a: { phq9: (number | null)[]; gad7: (number | null)[] }) => void; onCancel: () => void }) {
  const items = [...PHQ9.map(t => ({ s: 'phq9' as const, t })), ...GAD7.map(t => ({ s: 'gad7' as const, t }))]
  const [i, setI] = useState(0)
  const [vals, setVals] = useState<(number | null)[]>(items.map(() => null))
  const pick = (v: number) => {
    const next = vals.slice(); next[i] = v; setVals(next)
    if (i < items.length - 1) setTimeout(() => setI(i + 1), 160)
  }
  const done = vals.every(v => v !== null)
  return (
    <div>
      <p className="q-step">Вопрос {i + 1} из {items.length} · за последние 2 недели, как часто вас беспокоило</p>
      <div className="progress"><div style={{ width: `${((i + 1) / items.length) * 100}%` }} /></div>
      <p className="q-text">{items[i].t}</p>
      <div className="q-options" role="radiogroup">
        {OPTIONS.map((o, v) => (
          <button key={o} role="radio" aria-checked={vals[i] === v} aria-pressed={vals[i] === v} onClick={() => pick(v)}>{o}</button>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
        <button className="btn" disabled={i === 0} onClick={() => setI(i - 1)}>Назад</button>
        {i < items.length - 1
          ? <button className="btn" onClick={() => setI(i + 1)}>Пропустить</button>
          : <button className="btn primary" disabled={!done && vals.filter(v => v === null).length > 2} onClick={() => onDone({ phq9: vals.slice(0, 9), gad7: vals.slice(9) })}>Готово</button>}
        <button className="btn quiet" style={{ marginLeft: 'auto' }} onClick={onCancel}>Выйти</button>
      </div>
      <p className="faint" style={{ marginTop: 14 }}>Можно пропустить вопрос. Ответ на вопрос 9 — о мыслях причинить себе вред — особенно важен для врача.</p>
    </div>
  )
}
