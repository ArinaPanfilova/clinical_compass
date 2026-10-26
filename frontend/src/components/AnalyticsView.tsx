// Экран «Авиандр: наблюдение применения». Отчёт приходит с сервера готовым
// (kompas_core.analytics.aviandr_report); здесь только фильтры и показ.
import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import '../analytics.css'
import type {
  AdherenceBand, AnalyticsQuery, AviandrReport, AviandrReportFull, Composition, MaskedCount, StopReason,
} from '../analyticsTypes'
import {
  AGE_OPTIONS, SCALE_NAME, ageKey, cleanQuery, coursesWord, hiddenHint, isFiltered, num, pct, ci,
  reportKind, setAge, stopReasonRows,
} from './analytics/model'
import { BarList, CiAxis, CountUp, Num, RateRow, type BarItem } from './analytics/parts'
import { AnalyticsSkeleton } from './Skeleton'
import { TrajectoryPanel } from './analytics/TrajectoryChart'

export type { AnalyticsQuery, AviandrReport } from '../analyticsTypes'

type Role = 'doctor' | 'researcher'

// Пока отчёт не пришёл, оговорка всё равно видна (текст — как kompas_core.analytics.CAVEAT).
const DEFAULT_CAVEAT = 'Наблюдение без контрольной группы. Изменение шкалы не отделяет эффект препарата ' +
  'от естественного течения, регрессии к среднему и отбора пациентов.'
const DEFAULT_QUERY: AnalyticsQuery = { scale: 'gad7' }

const SEX = [['', 'Все'], ['Ж', 'Ж'], ['М', 'М']]
const INDICATION = [['', 'Все'], ['F41.1', 'F41.1 ГТР'], ['F43.2', 'F43.2 после COVID-19']]
const COMORBIDITY = [['', 'Все'], ['none', 'Нет'], ['cardiovascular', 'Сердечно-сосудистые'], ['endocrine', 'Эндокринные']]
const CONCOMITANT = [['', 'Все'], ['none', 'Нет'], ['antidepressant', 'Антидепрессант']]

const COMPOSITION_LABELS: Record<string, Record<string, string>> = {
  sex: { Ж: 'Женщины', М: 'Мужчины' },
  indication: { 'F41.1': 'F41.1 ГТР', 'F43.2': 'F43.2 после COVID-19' },
  comorbidity: { none: 'нет', cardiovascular: 'сердечно-сосудистые', endocrine: 'эндокринные' },
  concomitant: { none: 'нет', antidepressant: 'антидепрессант' },
}
const COMPOSITION_TITLES: [keyof Composition, string][] = [
  ['age', 'Возраст'], ['sex', 'Пол'], ['indication', 'Показание'], ['comorbidity', 'Коморбидность'], ['concomitant', 'Сопутствующая терапия'],
]

// Цвет причины отмены совпадает с цветом группы исхода на графике.
const REASON_COLOR: Partial<Record<StopReason, string>> = {
  adverse_event: 'var(--an-g-stopped_ae)', inefficacy: 'var(--an-g-stopped_inefficacy)',
}
const reasonColor = (r: string) => REASON_COLOR[r as StopReason] ?? 'var(--an-g-stopped_other)'

export function AnalyticsView({ role, fetchReport }: { role: Role; fetchReport: (q: AnalyticsQuery) => Promise<AviandrReport> }): JSX.Element {
  const [query, setQuery] = useState<AnalyticsQuery>(DEFAULT_QUERY)
  const [report, setReport] = useState<AviandrReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const fetchRef = useRef(fetchReport)
  fetchRef.current = fetchReport
  const seq = useRef(0)

  useEffect(() => {
    const id = ++seq.current
    setLoading(true)
    setError(null)
    fetchRef.current(cleanQuery(query))
      .then(r => { if (id === seq.current) { setReport(r); setLoading(false) } })
      .catch((e: unknown) => {
        if (id !== seq.current) return
        setError(e instanceof Error && e.message ? e.message : 'Сервер не ответил')
        setLoading(false)
      })
  }, [query, attempt, role])

  const k = report?.k_min ?? (role === 'researcher' ? 5 : 1)
  const n = report && report.n !== null ? report.n : null
  const subtitle = role === 'doctor'
    ? `Ваши пациенты${n !== null ? `, ${coursesWord(n)}` : ''}`
    : `Все курсы организации, обезличенно; группы меньше ${k} человек скрыты`
  const reset = () => setQuery(q => ({ scale: q.scale }))

  let body: ReactNode
  if (error) {
    body = (
      <div className="an-state" role="alert">
        <h2>Не удалось загрузить отчёт</h2>
        <p className="muted">{error}</p>
        <button className="btn primary" onClick={() => setAttempt(a => a + 1)}>Повторить</button>
      </div>
    )
  } else if (!report) {
    body = <AnalyticsSkeleton />
  } else if (reportKind(report) === 'suppressed') {
    body = (
      <div className="an-state">
        <h2>Показ скрыт</h2>
        <p className="muted">{'message' in report ? report.message : ''}</p>
        {isFiltered(query) && <button className="btn" onClick={reset}>Сбросить фильтры</button>}
      </div>
    )
  } else if (reportKind(report) === 'empty') {
    body = (
      <div className="an-state">
        <h2>Нет курсов под фильтр</h2>
        <p className="muted">Ослабьте условия отбора или сбросьте фильтры.</p>
        {isFiltered(query) && <button className="btn" onClick={reset}>Сбросить фильтры</button>}
      </div>
    )
  } else {
    body = <div className="an-dash view-in"><Dashboard r={report as AviandrReportFull} /></div>
  }

  return (
    <div className="an" aria-busy={loading}>
      <header className="an-head">
        <div className="an-title">
          <h1>Авиандр: наблюдение применения</h1>
          <p className="muted">{subtitle}</p>
        </div>
        {report?.synthetic && <span className="an-synthetic" title="Курсы сгенерированы по условиям инструкции; это не реальные пациенты">Синтетические данные</span>}
      </header>

      <Filters query={query} onChange={setQuery} onReset={reset} busy={loading && report !== null && !error} />

      <p className="an-caveat" role="note"><b>Оговорка.</b> {report?.caveat ?? DEFAULT_CAVEAT}</p>

      <div className={`an-body ${loading && report && !error ? 'is-stale' : ''}`}>{body}</div>
    </div>
  )
}

// ---------- Фильтры ----------

function Select({ label, value, options, onChange }: {
  label: string; value: string; options: string[][]; onChange: (v: string) => void
}) {
  const id = useId()
  return (
    <div className="an-field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="select" value={value} onChange={e => onChange(e.target.value)}>
        {options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
    </div>
  )
}

function Filters({ query, onChange, onReset, busy }: {
  query: AnalyticsQuery; onChange: (q: AnalyticsQuery) => void; onReset: () => void; busy: boolean
}) {
  const set = (key: keyof AnalyticsQuery) => (v: string) => onChange({ ...query, [key]: v })
  return (
    <div className="an-filters" role="search" aria-label="Фильтры курсов">
      <div className="an-field">
        <span id="an-period">Начало курса</span>
        <div className="an-period" role="group" aria-labelledby="an-period">
          <input type="date" className="an-date" aria-label="Начало курса с" value={query.start_from ?? ''}
            max={query.start_to || undefined} onChange={e => set('start_from')(e.target.value)} />
          <span className="faint">–</span>
          <input type="date" className="an-date" aria-label="Начало курса по" value={query.start_to ?? ''}
            min={query.start_from || undefined} onChange={e => set('start_to')(e.target.value)} />
        </div>
      </div>
      <Select label="Возраст" value={ageKey(query)} options={AGE_OPTIONS.map(o => [o.key, o.label])} onChange={v => onChange(setAge(query, v))} />
      <Select label="Пол" value={query.sex ?? ''} options={SEX} onChange={set('sex')} />
      <Select label="Показание" value={query.indication ?? ''} options={INDICATION} onChange={set('indication')} />
      <Select label="Коморбидность" value={query.comorbidity ?? ''} options={COMORBIDITY} onChange={set('comorbidity')} />
      <Select label="Сопутствующая терапия" value={query.concomitant ?? ''} options={CONCOMITANT} onChange={set('concomitant')} />
      <div className="an-field">
        <span id="an-scale">Шкала</span>
        <div className="seg" role="group" aria-labelledby="an-scale">
          {(['gad7', 'phq9'] as const).map(s => (
            <button key={s} aria-pressed={query.scale === s} onClick={() => onChange({ ...query, scale: s })}>{SCALE_NAME[s]}</button>
          ))}
        </div>
      </div>
      <div className="an-field an-actions">
        <button className="btn quiet" onClick={onReset} disabled={!isFiltered(query)}>Сбросить</button>
        {busy && <span className="an-busy" aria-live="polite">Обновляем…</span>}
      </div>
    </div>
  )
}

// ---------- Отчёт ----------

function Dashboard({ r }: { r: AviandrReportFull }) {
  const k = r.k_min
  return (
    <>
      <Kpis r={r} />
      <div className="an-grid">
        <div className="an-col">
          <TrajectoryPanel report={r} />
          <SafetyPanel r={r} />
        </div>
        <div className="an-col">
          <ResponsePanel r={r} />
          <StopReasonsPanel r={r} />
          <AdherencePanel r={r} />
        </div>
      </div>
      <section className="panel an-composition" aria-labelledby="an-comp-h">
        <div className="panel-head">
          <h2 id="an-comp-h">Контекст выборки</h2>
          <span className="faint">Состав курсов под текущим фильтром — с кем вы сравниваете</span>
        </div>
        <div className="an-comp-grid">
          {COMPOSITION_TITLES.map(([key, title]) => {
            const d = r.composition[key] ?? {}
            const items: BarItem[] = Object.entries(d).map(([v, c]) => ({ key: v, label: COMPOSITION_LABELS[key]?.[v] ?? v, value: c }))
            return (
              <div key={key} className="an-comp">
                <h3>{title}</h3>
                <BarList items={items} max={r.n} k={k} compact />
              </div>
            )
          })}
        </div>
        <p className="faint an-foot">Коморбидностей и сопутствующих препаратов у курса может быть несколько — сумма может превышать число курсов.</p>
      </section>
    </>
  )
}

const share = (v: MaskedCount, of: MaskedCount) => (v !== null && of ? `${pct(Math.round((1000 * v) / of) / 10)} назначенных` : '')

function Kpis({ r }: { r: AviandrReportFull }) {
  const k = r.k_min, kp = r.kpis
  const reasons = stopReasonRows(kp.by_reason, r.labels.stop_reasons, k)
  const total = reasons.reduce((s, x) => s + (x.value ?? k - 1), 0)
  const ae = reasons.find(x => x.key === 'adverse_event')
  const ineff = reasons.find(x => x.key === 'inefficacy')
  const others = reasons.filter(x => x.key !== 'adverse_event' && x.key !== 'inefficacy')
  const othersKnown = others.reduce((s, x) => s + (x.value ?? 0), 0)
  const othersHidden = others.some(x => x.value === null && k > 1)
  const b = r.benefit_index
  const bHidden = Boolean(b.hidden) || (b.numerator === null && k > 1)

  return (
    <section className="an-kpis" aria-label="Ключевые показатели">
      <div className="stats an-stats">
        <div className="stat">
          <span className="stat-label">Назначено</span>
          <span className="stat-value"><Num v={kp.assigned} k={k} animate /></span>
          <span className="stat-delta">курсов под фильтр</span>
        </div>
        <div className="stat">
          <span className="stat-label">Продолжают</span>
          <span className="stat-value"><Num v={kp.active} k={k} animate /></span>
          <span className="stat-delta">{share(kp.active, kp.assigned)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Завершили курс</span>
          <span className="stat-value"><Num v={kp.completed} k={k} animate /></span>
          <span className="stat-delta">{share(kp.completed, kp.assigned)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Отменили</span>
          <span className="stat-value"><Num v={kp.discontinued} k={k} animate /></span>
          {total > 0 && (
            <span className="an-stack" aria-hidden>
              {reasons.map(x => {
                const w = (x.value ?? k - 1) / total
                return w > 0 ? <span key={x.key} className={x.value === null ? 'ghost' : ''} title={`${x.label}: ${x.value ?? `<${k}`}`}
                  style={{ flexGrow: w, '--c': reasonColor(x.key) } as CSSProperties} /> : null
              })}
            </span>
          )}
          <span className="stat-delta an-reasons">
            {ae && <span><i style={{ background: reasonColor('adverse_event') }} />НЯ <Num v={ae.value} k={k} /></span>}
            {ineff && <span><i style={{ background: reasonColor('inefficacy') }} />нет эффекта <Num v={ineff.value} k={k} /></span>}
            {others.length > 0 && (
              <span title={others.map(x => `${x.label}: ${x.value ?? `<${k}`}`).join('\n')}>
                <i style={{ background: reasonColor('other') }} />другие {othersHidden ? `≥${num(othersKnown + 1)}` : num(othersKnown)}
              </span>
            )}
          </span>
        </div>
      </div>

      <div className="an-benefit">
        <span className="an-benefit-label">Индекс устойчивой пользы <span className="faint">· {SCALE_NAME[b.scale]}</span></span>
        <span className="an-benefit-value">
          {bHidden ? <span className="an-hidden" title={hiddenHint(k)}>&lt;{k}</span>
            : b.value_pct === null ? pct(null) : <CountUp value={b.value_pct} format={v => pct(Math.round(v * 10) / 10)} />}
        </span>
        <span className="an-benefit-ci">{!bHidden && b.ci95 ? `95 % ДИ ${ci(b.ci95)}` : bHidden ? hiddenHint(k) : ''}</span>
        <span className="an-benefit-of">
          <Num v={b.numerator} k={k} /> из {coursesWord(b.denominator)}
        </span>
        <details className="an-formula">
          <summary>Как считается</summary>
          <div className="an-formula-body">
            <p>{b.formula}</p>
            <p className="faint">Ответили: {num(b.components.responders)}. Серьёзные НЯ или отмена из-за НЯ: {num(b.components.with_harm)}. ДИ — метод Вильсона.</p>
          </div>
        </details>
      </div>
    </section>
  )
}

function ResponsePanel({ r }: { r: AviandrReportFull }) {
  const res = r.response, k = r.k_min
  return (
    <section className="panel an-resp" aria-labelledby="an-resp-h">
      <div className="panel-head">
        <h2 id="an-resp-h">Ответ на терапию</h2>
        <span className="faint">{SCALE_NAME[res.scale]}, последнее наблюдение</span>
      </div>
      <div className="an-rates">
        <RateRow label="Ответ" def={res.definitions.response} rate={res.response} denom={res.denominator} k={k} tone="brand" />
        <RateRow label="Клинически значимое улучшение" def={res.definitions.mcid} rate={res.mcid} denom={res.denominator} k={k} tone="brand" />
        <RateRow label="Ремиссия" def={res.definitions.remission} rate={res.remission} denom={res.denominator} k={k} tone="brand" />
        <CiAxis />
      </div>
      <p className="faint an-foot">
        Знаменатель — {coursesWord(res.denominator)} с исходным измерением; курс без повторного измерения считается курсом без ответа.
      </p>
    </section>
  )
}

function StopReasonsPanel({ r }: { r: AviandrReportFull }) {
  const k = r.k_min
  const rows = stopReasonRows(r.kpis.by_reason, r.labels.stop_reasons, k)
  const max = Math.max(k - 1, ...rows.map(x => x.value ?? 0))
  return (
    <section className="panel an-stop" aria-labelledby="an-stop-h">
      <div className="panel-head">
        <h2 id="an-stop-h">Причины отмены</h2>
        <span className="faint">отменено <Num v={r.kpis.discontinued} k={k} /> из <Num v={r.kpis.assigned} k={k} /></span>
      </div>
      {rows.every(x => x.value === 0)
        ? <p className="empty">Отмен нет.</p>
        : <BarList items={rows.map(x => ({ key: x.key, label: x.label, value: x.value, color: reasonColor(x.key) }))} max={max} k={k} />}
    </section>
  )
}

const ADH_BANDS: [AdherenceBand, string, string][] = [
  ['≥80%', '≥ 80 %', 'var(--an-adh-1)'], ['50–79%', '50–79 %', 'var(--an-adh-2)'], ['<50%', '< 50 %', 'var(--an-adh-3)'],
]

function AdherencePanel({ r }: { r: AviandrReportFull }) {
  const a = r.adherence, k = r.k_min
  // Длина — доля курсов с отметками, а не доля от самой длинной полосы.
  const max = a.courses_with_data || Math.max(k - 1, ...ADH_BANDS.map(([b]) => a.bands[b] ?? 0))
  return (
    <section className="panel an-adh" aria-labelledby="an-adh-h">
      <div className="panel-head">
        <h2 id="an-adh-h">Приверженность</h2>
        <span className="faint">курсов с отметками: {num(a.courses_with_data)}</span>
      </div>
      <div className="an-figs">
        <div><b>{pct(a.median_pct)}</b><span>медиана отмеченных приёмов</span></div>
        <div><b className="unk">{pct(a.unknown_share_pct)}</b><span>дней без отметки</span></div>
      </div>
      <h3 className="an-sub-h">Доля отмеченных приёмов на курс</h3>
      <BarList items={ADH_BANDS.map(([b, label, color]) => ({ key: b, label, value: a.bands[b], color }))} max={max} k={k} />
      <p className="faint an-foot">{a.note}</p>
    </section>
  )
}

const SEVERITY: [keyof Omit<AviandrReportFull['safety']['by_term'][number], 'term'>, string][] = [
  ['mild', 'Лёгкая'], ['moderate', 'Умеренная'], ['severe', 'Тяжёлая'], ['unknown', 'Не оценена'], ['total', 'Всего'],
]

function SafetyPanel({ r }: { r: AviandrReportFull }) {
  const s = r.safety, k = r.k_min
  return (
    <section className="panel an-safety" aria-labelledby="an-saf-h">
      <div className="panel-head">
        <h2 id="an-saf-h">Безопасность</h2>
        <span className="faint">нежелательные явления, {coursesWord(s.courses)}</span>
      </div>
      <div className="an-rates inline">
        <RateRow label="Курсы с НЯ" rate={s.with_ae} denom={s.courses} k={k} tone="rx" />
        <RateRow label="Серьёзные НЯ" rate={s.serious} denom={s.courses} k={k} tone="rx" />
        <RateRow label="Отмена из-за НЯ" rate={s.stopped_due_to_ae} denom={s.courses} k={k} tone="rx" />
        <CiAxis />
      </div>
      {s.by_term.length === 0 ? <p className="empty an-gap">НЯ не зарегистрированы.</p> : (
        <div className="an-table-wrap an-gap">
          <table className="an-table an-ae">
            <caption className="sr-only">Нежелательные явления по терминам и тяжести, число случаев</caption>
            <thead>
              <tr><th scope="col">Термин</th>{SEVERITY.map(([key, t]) => <th key={key} scope="col" className="num">{t}</th>)}</tr>
            </thead>
            <tbody>
              {s.by_term.map(row => (
                <tr key={row.term}>
                  <th scope="row">{row.term}</th>
                  {SEVERITY.map(([key]) => (
                    <td key={key} className={`num ${key === 'total' ? 'total' : ''} ${row[key] === 0 ? 'zero' : ''}`}><Num v={row[key]} k={k} /></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="faint an-foot">{s.note} Тяжесть «не оценена» не равна «лёгкой».</p>
    </section>
  )
}
