import { useCallback, useEffect, useState } from 'react'
import { api, type Mode } from '../api'
import type { Message } from '../types'

// Защищённая переписка врач ↔ пациент. Не канал экстренной помощи:
// «прочитано» не значит «помощь оказана», клинические решения фиксируются в плане, а не в чате.

const time = (s: string) => new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export function MessagesPanel({ pid, mode, role, tick = 0 }: { pid: string; mode: Mode; role: 'doctor' | 'patient'; tick?: number }) {
  const [msgs, setMsgs] = useState<Message[] | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (mode !== 'live') { setMsgs([]); return }
    try {
      const ms = await api.messages(pid)
      setMsgs(ms)
      // Лента открыта получателем — отмечаем прочитанным то, что адресовано ему
      for (const m of ms) if (m.sender_role !== role && !m.read_at) api.readMessage(m.id).catch(() => {})
    } catch (e) { setErr((e as Error).message) }
  }, [pid, mode, role])

  useEffect(() => {
    load()
    if (mode !== 'live') return
    const t = setInterval(load, 10_000)
    return () => clearInterval(t)
  }, [load, mode, tick])

  const send = async () => {
    if (!text.trim()) return
    setBusy(true); setErr(null)
    try {
      await api.sendMessage(pid, text.trim())
      setText('')
      await load()
    } catch (e) { setErr(`Не отправилось: ${(e as Error).message}. Текст сохранён — попробуйте ещё раз.`) } finally { setBusy(false) }
  }

  const label = role === 'patient' ? 'Вопрос врачу' : 'Ответ пациенту'
  return (
    <div className="messages">
      {mode !== 'live' && <p className="faint">Переписка работает, когда подключён сервер.</p>}
      {msgs && msgs.length === 0 && mode === 'live' && <p className="empty">Сообщений пока нет.</p>}
      <ul className="thread">
        {msgs?.map(m => {
          const mine = m.sender_role === role
          return (
            <li key={m.id} className={`bubble ${mine ? 'mine' : 'theirs'}`}>
              <p>{m.text}</p>
              <span className="bubble-meta">
                {mine ? '' : m.sender_role === 'doctor' ? 'Врач · ' : 'Пациент · '}{time(m.created_at)}
                {mine && <> · {m.read_at ? 'прочитано' : m.delivered_at ? 'доставлено' : 'отправлено'}</>}
              </span>
            </li>
          )
        })}
      </ul>
      {err && <p className="warn-line">{err}</p>}
      <textarea className="field" aria-label={label} placeholder={label} value={text} onChange={e => setText(e.target.value)} disabled={mode !== 'live'} />
      <button className={role === 'patient' ? 'big-btn' : 'btn primary'} disabled={busy || !text.trim() || mode !== 'live'} onClick={send}>
        {role === 'patient' ? 'Отправить сообщение' : 'Отправить'}
      </button>
    </div>
  )
}
