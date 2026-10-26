import { useState } from 'react'
import type { TherapyGuide } from '../types'

// Справка по действующим КР Минздрава для диагноза пациента. Не назначение: препарат выбирает врач.
// Препараты вне зарегистрированного показания помечены — система их не предлагает.

const MAIN_LINES = new Set(['first'])

export function TherapyOptions({ guides }: { guides: TherapyGuide[] }) {
  const [all, setAll] = useState(false)
  if (!guides.length) return <p className="empty">Для диагнозов пациента в базе нет клинических рекомендаций. Решение — по общим принципам, с консультацией психиатра при необходимости.</p>
  return (
    <div className="therapy">
      {guides.map(g => {
        const shown = all ? g.options : g.options.filter(o => MAIN_LINES.has(o.line) || o.drugs.some(d => d.current || d.mnn === 'маритупирдин'))
        return (
          <div key={g.guideline.id} className="therapy-guide">
            <p className="therapy-src">
              КР «{g.guideline.title}», {g.guideline.year}, ID {g.guideline.id} — <a href={g.guideline.url} target="_blank" rel="noreferrer">рубрикатор Минздрава</a>
            </p>
            {!g.diagnosis_confirmed && <p className="warn-line">Диагноз предварительный: справка по КР — после подтверждения диагноза.</p>}
            <ul className="therapy-list">
              {shown.map(o => (
                <li key={o.label} className={`line-${o.line}`}>
                  <div className="therapy-head">
                    <span className="line-tag">{o.line_label}</span>
                    <b>{o.label}</b>
                    <span className="faint">{o.evidence}</span>
                  </div>
                  {o.drugs.length > 0 && (
                    <div className="drug-chips">
                      {o.drugs.map(d => (
                        <span key={d.mnn} className={`drug-chip ${d.off_label ? 'off' : ''} ${d.current ? 'cur' : ''}`}
                          title={`Показание в инструкции: ${d.indication}`}>
                          {d.mnn}{d.trade_names?.length ? ` (${d.trade_names.join(', ')})` : ''}
                          {d.current && ' · назначен'}{d.off_label && ' · вне показания'}
                        </span>
                      ))}
                    </div>
                  )}
                  <p className="faint">{o.note} <span className="therapy-ref">{o.source}</span></p>
                </li>
              ))}
            </ul>
            <button className="btn quiet" onClick={() => setAll(a => !a)}>{all ? 'Только первая линия' : `Все линии (${g.options.length})`}</button>
            <details className="therapy-mon"><summary>Контроль эффекта по КР</summary><p className="faint">{g.monitoring}</p></details>
          </div>
        )
      })}
      <p className="faint source">{guides[0].note}</p>
    </div>
  )
}
