import { useState } from 'react'
import { api } from '../api'
import { SAFETY_LABELS } from '../content'
import type { DocumentExtraction, PatientBundle } from '../types'

// Документ пациента → факты с цитатами. Ничего не попадает в карточку без подтверждения врача:
// по умолчанию отмечены только новые сведения; противоречия с карточкой врач разбирает сам.

const KIND = { new: 'новое', same: 'уже в карточке', conflict: 'противоречит карточке' } as const
const yesNo = (v: boolean | null) => v === true ? 'да' : v === false ? 'нет' : 'неизвестно'

export function DocumentDialog({ pid, onClose, onApplied }: { pid: string; onClose: () => void; onApplied: (b: PatientBundle) => void }) {
  const [text, setText] = useState('')
  const [res, setRes] = useState<DocumentExtraction | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const run = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await api.extractDocument(pid, text)
      setRes(r)
      setPicked(new Set(r.diff.filter(d => d.kind === 'new').map(d => d.key)))
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const apply = async () => {
    if (!res) return
    setBusy(true); setErr(null)
    try {
      const facts = Object.fromEntries(res.diff.filter(d => picked.has(d.key)).map(d => [d.key, d.extracted]))
      onApplied(await api.updateSafety(pid, facts, 'document', res.document_id))
      onClose()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const toggle = (k: string) => setPicked(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n })
  const x = res?.extraction

  return (
    <div className="modal-back page" role="dialog" aria-modal="true" aria-labelledby="doc-title">
      <div className="sheet wide">
        <h2 id="doc-title">Документ пациента</h2>
        <p className="faint">Выписка, осмотр или направление. Сведения извлекаются правилами со ссылкой на фрагмент текста;
          в карточку попадает только то, что вы подтвердите.</p>
        {!res ? (
          <>
            <label className="doc-label">Текст документа
              <textarea className="field doc-text" value={text} onChange={e => setText(e.target.value)}
                placeholder="Вставьте текст выписки или осмотра" />
            </label>
            {err && <p className="warn-line">{err}</p>}
            <div className="doc-actions">
              <button className="btn primary" disabled={busy || !text.trim()} onClick={run}>{busy ? 'Извлекаем…' : 'Извлечь сведения'}</button>
              <button className="btn quiet" onClick={onClose}>Отмена</button>
            </div>
          </>
        ) : (
          <>
            <p className="doc-status">Статус: извлечено, не проверено{x!.document_date ? ` · документ от ${new Date(x!.document_date).toLocaleDateString('ru-RU')}` : ''}</p>
            <h3>Профиль безопасности</h3>
            {res.diff.length === 0 && <p className="empty">Сведений о противопоказаниях в тексте не найдено — профиль не меняется.</p>}
            <ul className="doc-facts">
              {res.diff.map(d => (
                <li key={d.key} className={`kind-${d.kind}`}>
                  <label>
                    <input type="checkbox" checked={picked.has(d.key)} disabled={d.kind === 'same'} onChange={() => toggle(d.key)} />
                    <span className="doc-fact"><b>{SAFETY_LABELS[d.key] ?? d.key}: {yesNo(d.extracted)}</b>
                      <span className={`doc-kind ${d.kind}`}>{KIND[d.kind]}{d.kind === 'conflict' ? ` (сейчас: ${yesNo(d.current)})` : ''}</span>
                    </span>
                  </label>
                  <q className="doc-quote">{d.evidence.quote}</q>
                </li>
              ))}
            </ul>
            <div className="doc-grid">
              <div><h3>Диагнозы</h3>
                {x!.diagnoses.length ? <ul className="list">{x!.diagnoses.map((d, i) => <li key={i}><b>{d.code}</b>{d.status === 'suspected' ? ' (предварительный)' : ''} — <q className="doc-quote">{d.evidence.quote}</q></li>)}</ul> : <p className="empty">Не найдены.</p>}
              </div>
              <div><h3>Препараты</h3>
                {x!.medications.length ? <ul className="list">{x!.medications.map((m, i) => <li key={i}><b>{m.mnn}</b>{m.dose_mg ? ` ${m.dose_mg} мг` : ''}{m.status === 'cancelled' ? ' (отменён)' : ''} — <q className="doc-quote">{m.evidence.quote}</q></li>)}</ul> : <p className="empty">Не найдены.</p>}
              </div>
              <div><h3>Аллергии</h3>
                {x!.allergies === null ? <p className="empty">Не упомянуты.</p> : x!.allergies.length === 0 ? <p className="empty">Отрицает.</p>
                  : <ul className="list">{x!.allergies.map((a, i) => <li key={i}><b>{a.name}</b> — <q className="doc-quote">{a.evidence.quote}</q></li>)}</ul>}
              </div>
            </div>
            <p className="faint">Диагнозы, препараты и аллергии показаны для сверки с карточкой. Не упомянутое в тексте остаётся «неизвестно», а не «нет».</p>
            {err && <p className="warn-line">{err}</p>}
            <div className="doc-actions">
              <button className="btn primary" disabled={busy || picked.size === 0} onClick={apply}>Подтвердить выбранное</button>
              <button className="btn quiet" onClick={() => setRes(null)}>Назад к тексту</button>
              <button className="btn quiet" onClick={onClose}>Закрыть</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
