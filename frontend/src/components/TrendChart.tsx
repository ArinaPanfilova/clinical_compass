// Динамика шкалы одного пациента: зоны тяжести, сумма баллов по датам, начало терапии.
// SVG в реальную ширину контейнера — подписи остаются 11–12 px на любом экране.
// Наведение или стрелки с клавиатуры показывают значение ближайшей анкеты.
import { useState, type KeyboardEvent, type PointerEvent } from 'react'
import { BANDS } from '../content'
import { useWidth } from '../hooks'
import type { ScalePoint } from '../types'

interface Props {
  scale: 'phq9' | 'gad7'
  points: ScalePoint[]
  therapyStarts?: { date: string; label: string }[]
  expectedIntervalDays?: number
  compact?: boolean
}

const BAND_FILL = ['var(--band-1)', 'var(--band-2)', 'var(--band-3)', 'var(--band-4)', 'var(--band-5)']
const DAY = 86_400_000

const fmt = (d: string) => new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
const fmtLong = (d: string) => new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })

export function TrendChart({ scale, points, therapyStarts = [], expectedIntervalDays = 14, compact }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hi, setHi] = useState<number | null>(null)
  const bands = BANDS[scale]
  const yMax = bands[bands.length - 1].max
  const label = scale === 'phq9' ? 'PHQ-9' : 'GAD-7'

  const W = Math.max(width, 240)
  const narrow = W < 520
  const H = compact ? 168 : 236
  const pad = { l: 30, r: compact || narrow ? 12 : 116, t: compact ? 10 : 18, b: 26 }
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b

  const dates = [...points.map(p => +new Date(p.date)), ...therapyStarts.map(t => +new Date(t.date))]
  let x0 = Math.min(...dates), x1 = Math.max(...dates)
  const empty = !isFinite(x0)
  if (x1 - x0 < 7 * DAY) { x0 -= 7 * DAY; x1 += 7 * DAY }
  const inset = 18   // точки не прилипают к краям и подписям зон
  const x = (d: string) => pad.l + inset + ((+new Date(d) - x0) / (x1 - x0)) * (iw - 2 * inset)
  const y = (v: number) => pad.t + ih - (v / yMax) * ih

  const scored = points.filter(p => p.total !== null) as (ScalePoint & { total: number })[]
  const segs = scored.slice(1).map((p, i) => {
    const a = scored[i]
    const gap = (+new Date(p.date) - +new Date(a.date)) / DAY > expectedIntervalDays * 1.5
    return { a, b: p, gap }
  })
  // Подписи значений — у каждой точки, пока их немного; на длинном ряду — первая, последняя и максимум
  const maxTotal = Math.max(...scored.map(p => p.total))
  const labelled = (i: number) => scored.length <= 8 || i === 0 || i === scored.length - 1 || scored[i].total === maxTotal

  const nearest = (px: number) => {
    let best = 0
    scored.forEach((p, i) => { if (Math.abs(x(p.date) - px) < Math.abs(x(scored[best].date) - px)) best = i })
    return best
  }
  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.ownerSVGElement!.getBoundingClientRect()
    setHi(nearest(e.clientX - box.left))
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const d = e.key === 'ArrowRight' ? 1 : -1
      setHi(i => Math.min(scored.length - 1, Math.max(0, (i ?? (d > 0 ? -1 : scored.length)) + d)))
    } else if (e.key === 'Escape') setHi(null)
  }

  if (empty) return <p className="muted">Анкет пока нет.</p>
  const cur = hi !== null ? scored[hi] : null
  const summary = `Динамика ${label}. ${scored.map(p => `${fmt(p.date)}: ${p.total}`).join(', ')}`

  return (
    <figure className={`chart ${compact ? 'compact' : ''}`} style={{ margin: 0 }} aria-label={`Динамика ${label}`}>
      <div ref={ref} className="chart-box" tabIndex={compact || !scored.length ? undefined : 0} onKeyDown={onKey} onBlur={() => setHi(null)}
        aria-label={compact ? undefined : `${summary}. Стрелками влево и вправо можно переходить по анкетам.`}>
        {width > 0 && (
          <svg key={scale} width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary}>
            {bands.map((b, i) => {
              const top = i < bands.length - 1 ? bands[i + 1].min : yMax
              return (
                <g key={b.label}>
                  <rect x={pad.l} width={iw} y={y(top)} height={y(b.min) - y(top)} fill={BAND_FILL[i]} />
                  {i > 0 && <line className="band-edge" x1={pad.l} x2={pad.l + iw} y1={y(b.min)} y2={y(b.min)} />}
                  {!compact && !narrow && <text className="band-label" x={pad.l + iw + 8} y={(y(b.min) + y(top)) / 2 + 4}>{b.label}</text>}
                  <text className="axis" x={pad.l - 6} y={y(b.min) + 4} textAnchor="end">{b.min}</text>
                </g>
              )
            })}
            <text className="axis" x={pad.l - 6} y={y(yMax) + 4} textAnchor="end">{yMax}</text>

            {therapyStarts.map(t => (
              <g key={t.date + t.label} className="rx-mark">
                <line x1={x(t.date)} x2={x(t.date)} y1={pad.t} y2={pad.t + ih} />
                {!compact && <text className="axis rx-label" x={x(t.date) + 5} y={pad.t + 11}>{t.label}</text>}
              </g>
            ))}

            {scored.map(p => (
              <text key={'x' + p.date} className="axis" x={x(p.date)} y={H - 8} textAnchor="middle">{fmt(p.date)}</text>
            ))}
            {points.filter(p => p.total === null).map(p => (
              <g key={'na' + p.date}>
                <line x1={x(p.date)} x2={x(p.date)} y1={pad.t + ih - 10} y2={pad.t + ih} className="na-mark" />
                {!compact && <text className="axis" x={x(p.date)} y={pad.t + ih - 14} textAnchor="middle">н/д</text>}
              </g>
            ))}

            {cur && <line className="cross" x1={x(cur.date)} x2={x(cur.date)} y1={pad.t} y2={pad.t + ih} />}

            <g className="series draw-in">
              {segs.map(({ a, b, gap }, i) => (
                <line key={i} className={`seg-line ${gap ? 'gap' : ''}`} x1={x(a.date)} y1={y(a.total)} x2={x(b.date)} y2={y(b.total)} />
              ))}
              {scored.map((p, i) => (
                <g key={p.date + p.total}>
                  <circle className={`pt ${p.prorated ? 'prorated' : ''} ${hi === i ? 'on' : ''}`} cx={x(p.date)} cy={y(p.total)} r={hi === i ? 7 : 5.5} />
                  {!compact && labelled(i) && <text className="val" x={x(p.date)} y={y(p.total) - 11} textAnchor="middle">{p.total}</text>}
                </g>
              ))}
            </g>
            {!compact && scored.length > 0 && (
              <rect className="hit" x={pad.l} y={pad.t} width={iw} height={ih + pad.b}
                onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHi(null)} />
            )}
          </svg>
        )}
        {cur && (
          <div className="an-tip chart-tip" style={x(cur.date) < W * 0.6 ? { left: x(cur.date) + 14 } : { right: W - x(cur.date) + 14 }} role="status">
            <div className="an-tip-head">{fmtLong(cur.date)}</div>
            <div className="an-tip-row">
              <i style={{ borderColor: 'var(--viz-line)' }} />
              <b>{cur.total}</b><span className="faint">из {yMax} · {cur.category_label?.toLowerCase() ?? 'без градации'}</span>
              {cur.prorated && <span className="an-tip-label">пересчитано при пропусках: {cur.missing_items.length} пункт(а)</span>}
            </div>
          </div>
        )}
      </div>
      {!compact && (
        <figcaption className="chart-legend">
          <span><i />сумма баллов</span>
          <span><i className="dash" />разрыв больше {Math.round(expectedIntervalDays * 1.5)} дней</span>
          <span><i className="ring" />пересчитано при пропусках</span>
          {therapyStarts.length > 0 && <span><i className="rx" />начало терапии</span>}
        </figcaption>
      )}
    </figure>
  )
}
