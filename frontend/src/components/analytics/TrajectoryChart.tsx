// Главный график: медиана шкалы по неделям 0–12 по группам исхода, полоса Q1–Q3.
// Ручной SVG в реальную ширину контейнера, чтобы подписи оставались 11–12 px на любом экране.
import { useState, type KeyboardEvent, type PointerEvent } from 'react'
import { BANDS } from '../../content'
import type { AviandrReportFull, OutcomeGroup, TrajectoryPoint } from '../../analyticsTypes'
import { useWidth } from '../../hooks'
import { SCALE_MAX, SCALE_NAME, SCALE_TICKS, WEEK_STEP, bandPath, hiddenHint, linePath, num, segments } from './model'
import { Num } from './parts'

export const GROUPS: OutcomeGroup[] = ['continued', 'stopped_ae', 'stopped_inefficacy', 'stopped_other']
export const groupColor = (g: OutcomeGroup) => `var(--an-g-${g})`
const WEEKS = [0, 2, 4, 6, 8, 10, 12]
const LAST = WEEKS[WEEKS.length - 1]

const at = (pts: TrajectoryPoint[] | undefined, week: number) => pts?.find(p => p.week === week)
const iqr = (p: TrajectoryPoint) => `${num(p.q1 ?? 0)}–${num(p.q3 ?? 0)}`

export function TrajectoryPanel({ report }: { report: AviandrReportFull }) {
  const [table, setTable] = useState(false)
  const [hover, setHover] = useState<OutcomeGroup | null>(null)
  const [pinned, setPinned] = useState<OutcomeGroup | null>(null)
  const k = report.k_min
  const groups = GROUPS.filter(g => report.trajectories[g]?.length)
  const anyHidden = groups.some(g => report.trajectories[g].some(p => p.hidden))
  const name = SCALE_NAME[report.scale]

  return (
    <section className="panel an-traj" aria-labelledby="an-traj-h">
      <div className="panel-head">
        <div>
          <h2 id="an-traj-h">Динамика {name} по исходу курса</h2>
          <p className="faint">Медиана и межквартильный размах (Q1–Q3) по неделям, 0–{SCALE_MAX[report.scale]} баллов</p>
        </div>
        <button className="btn quiet an-toggle" aria-pressed={table} onClick={() => setTable(t => !t)}>
          {table ? 'График' : 'Таблица'}
        </button>
      </div>

      <div className="an-legend" role="group" aria-label="Группы исхода">
        {groups.map(g => {
          const first = report.trajectories[g][0]
          return (
            <button key={g} className="an-legend-item" aria-pressed={pinned === g}
              onPointerEnter={() => setHover(g)} onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(g)} onBlur={() => setHover(null)}
              onClick={() => setPinned(p => (p === g ? null : g))}
              title="Выделить группу и показать её полосу Q1–Q3">
              <i className={`g-${g}`} style={{ borderColor: groupColor(g) }} />
              <span>{report.labels.groups[g]}</span>
              <span className="faint" title="Курсов с измерением на неделе 0">n&nbsp;=&nbsp;<Num v={first?.week === 0 ? first.n : null} k={k} /></span>
            </button>
          )
        })}
        <span className="an-legend-note"><i className="band" />Q1–Q3 выбранной группы</span>
        {anyHidden && <span className="an-legend-note">&lt;{k} под осью — {hiddenHint(k)}</span>}
      </div>

      {groups.length === 0
        ? <p className="empty">Повторных измерений {name} под этот фильтр нет.</p>
        : table ? <TrajectoryTable report={report} groups={groups} /> : <TrajectoryChart report={report} groups={groups} active={hover ?? pinned} />}
    </section>
  )
}

function TrajectoryChart({ report, groups, active }: { report: AviandrReportFull; groups: OutcomeGroup[]; active: OutcomeGroup | null }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [week, setWeek] = useState<number | null>(null)
  const k = report.k_min
  const scale = report.scale
  const max = SCALE_MAX[scale]

  // «<k» под осью: где у группы точка скрыта. Несколько групп в одну неделю — столбиком.
  const hiddenMarks: { g: OutcomeGroup; week: number; row: number }[] = []
  for (const g of groups) for (const p of report.trajectories[g]) if (p.hidden) {
    hiddenMarks.push({ g, week: p.week, row: hiddenMarks.filter(m => m.week === p.week).length })
  }
  const rows = hiddenMarks.reduce((m, h) => Math.max(m, h.row + 1), 0)

  const W = Math.max(width, 300)
  const narrow = W < 560
  const plotH = narrow ? 220 : 280
  const pad = { l: 30, r: narrow ? 12 : 120, t: 10, b: 28 + (rows ? 8 + rows * 16 : 0) }
  const H = pad.t + plotH + pad.b
  const inset = 12
  const x0 = pad.l + inset, x1 = W - pad.r - inset
  const x = (w: number) => x0 + (w / LAST) * (x1 - x0)
  const y = (v: number) => pad.t + (1 - v / max) * plotH
  const bands = BANDS[scale]

  const pick = (px: number) => Math.min(LAST, Math.max(0, Math.round(((px - x0) / (x1 - x0)) * (LAST / WEEK_STEP)) * WEEK_STEP))
  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.ownerSVGElement!.getBoundingClientRect()
    setWeek(pick(e.clientX - box.left))
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const d = e.key === 'ArrowRight' ? WEEK_STEP : -WEEK_STEP
      setWeek(w => Math.min(LAST, Math.max(0, (w ?? -d) + d)))
    } else if (e.key === 'Escape') setWeek(null)
  }

  const order = active ? [...groups.filter(g => g !== active), active] : groups
  // Полоса Q1–Q3 — у одной группы: выбранной в легенде, иначе у самой большой («продолжают»).
  // Четыре полупрозрачные полосы на неделях 0–6 сливаются в пятно.
  const band = active ?? groups[0]
  const summary = groups.map(g => `${report.labels.groups[g]}: ` + report.trajectories[g]
    .map(p => p.hidden ? `неделя ${p.week} — скрыто` : `неделя ${p.week} — ${num(p.median ?? 0)} (${iqr(p)}), n ${p.n}`).join('; ')).join('. ')

  return (
    <div ref={ref} className="an-chart" tabIndex={0} onKeyDown={onKey} onFocus={() => setWeek(w => w ?? 0)} onBlur={() => setWeek(null)}
      aria-label={`График ${SCALE_NAME[scale]} по неделям. Стрелки влево и вправо — переход по неделям.`}>
      {width > 0 && (
        <svg key={scale} width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary}>
          {/* градации тяжести: тонкие линии и подписи справа */}
          {bands.map((b, i) => {
            const top = i < bands.length - 1 ? bands[i + 1].min : max
            return (
              <g key={b.label}>
                {b.min > 0 && <line className="an-gl" x1={pad.l} x2={W - pad.r} y1={y(b.min)} y2={y(b.min)} />}
                {!narrow && <text className="an-band-label" x={W - pad.r + 10} y={(y(b.min) + y(top)) / 2 + 4}>{b.label}</text>}
              </g>
            )
          })}
          <line className="an-base" x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} />
          {SCALE_TICKS[scale].map(t => <text key={t} className="an-axis" x={pad.l - 8} y={y(t) + 4} textAnchor="end">{t}</text>)}
          {WEEKS.map(w => (
            <text key={w} className="an-axis" x={x(w)} y={pad.t + plotH + 18} textAnchor="middle">{w === LAST ? `${w} нед.` : w}</text>
          ))}

          {order.map(g => {
            const runs = segments(report.trajectories[g])
            const dim = active !== null && active !== g
            return (
              <g key={g} className={`an-series g-${g} ${dim ? 'dim' : ''} ${active === g ? 'on' : ''}`} style={{ color: groupColor(g) }}>
                <g className="draw-in" style={{ animationDelay: `${groups.indexOf(g) * 120}ms` }}>
                  {/* полоса Q1–Q3: заливка + тонкие края, чтобы граница читалась и на тёмном фоне */}
                  {g === band && runs.map((r, i) => (
                    <g key={'b' + i} className="an-iqr-g">
                      <path className="an-iqr" d={bandPath(r, x, y)} />
                      {r.length > 1 && <path className="an-iqr-edge" d={linePath(r.map(p => ({ ...p, median: p.q1 })), x, y)} />}
                      {r.length > 1 && <path className="an-iqr-edge" d={linePath(r.map(p => ({ ...p, median: p.q3 })), x, y)} />}
                    </g>
                  ))}
                  {runs.map((r, i) => r.length > 1 && <path key={'l' + i} className="an-line" d={linePath(r, x, y)} />)}
                  {runs.flatMap((r, i) => (r.length > 1 ? [r[0], r[r.length - 1]] : [r[0]]).map((p, j) => (
                    <circle key={`d${i}-${j}`} className="an-dot" cx={x(p.week)} cy={y(p.median)} r={4} />
                  )))}
                </g>
              </g>
            )
          })}

          {hiddenMarks.map(m => {
            const yy = pad.t + plotH + 34 + m.row * 16
            const dim = active !== null && active !== m.g
            return (
              <g key={m.g + m.week} className={`an-hidden-mark ${dim ? 'dim' : ''}`}>
                <circle cx={x(m.week) - 9} cy={yy - 4} r={3.5} style={{ fill: groupColor(m.g) }} />
                <text className="an-axis" x={x(m.week) - 2} y={yy}>&lt;{k}<title>{`${report.labels.groups[m.g]}, неделя ${m.week}: ${hiddenHint(k)}`}</title></text>
              </g>
            )
          })}

          {week !== null && (
            <g className="an-cross" pointerEvents="none">
              <line x1={x(week)} x2={x(week)} y1={pad.t} y2={pad.t + plotH} />
              {groups.map(g => {
                const p = at(report.trajectories[g], week)
                return p && !p.hidden && p.median !== null
                  ? <circle key={g} className="an-dot on" cx={x(week)} cy={y(p.median)} r={4.5} style={{ color: groupColor(g) }} />
                  : null
              })}
            </g>
          )}
          <rect className="an-hit" x={pad.l} y={pad.t} width={W - pad.l - pad.r} height={plotH + 24}
            onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setWeek(null)} />
        </svg>
      )}
      {week !== null && (
        <div className="an-tip" style={x(week) < W * 0.55 ? { left: x(week) + 14 } : { right: W - x(week) + 14 }} role="status">
          <div className="an-tip-head">Неделя {week}</div>
          {groups.map(g => {
            const p = at(report.trajectories[g], week)
            if (!p) return null
            return (
              <div key={g} className="an-tip-row">
                <i className={`g-${g}`} style={{ borderColor: groupColor(g) }} />
                {p.hidden
                  ? <><b className="an-hidden">&lt;{k}</b><span className="faint">{hiddenHint(k)}</span></>
                  : <><b>{num(p.median ?? 0)}</b><span className="faint">Q1–Q3 {iqr(p)} · n {p.n}</span></>}
                <span className="an-tip-label">{report.labels.groups[g]}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function TrajectoryTable({ report, groups }: { report: AviandrReportFull; groups: OutcomeGroup[] }) {
  const k = report.k_min
  return (
    <div className="an-table-wrap">
      <table className="an-table an-traj-table">
        <caption className="sr-only">{SCALE_NAME[report.scale]}: медиана (Q1–Q3) и число курсов по неделям</caption>
        <thead>
          <tr><th scope="col">Неделя</th>{groups.map(g => <th key={g} scope="col">{report.labels.groups[g]}</th>)}</tr>
        </thead>
        <tbody>
          {WEEKS.map(w => (
            <tr key={w}>
              <th scope="row">{w}</th>
              {groups.map(g => {
                const p = at(report.trajectories[g], w)
                return (
                  <td key={g}>
                    {!p ? <span className="faint">—</span>
                      : p.hidden ? <Num v={null} k={k} />
                      : <>{num(p.median ?? 0)} <span className="faint">({iqr(p)}), n {p.n}</span></>}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
