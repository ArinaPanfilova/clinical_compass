import { BANDS } from '../content'
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

function fmt(d: string) {
  return new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

export function TrendChart({ scale, points, therapyStarts = [], expectedIntervalDays = 14, compact }: Props) {
  const bands = BANDS[scale]
  const yMax = bands[bands.length - 1].max
  const W = 640, H = compact ? 170 : 250
  const pad = { l: 34, r: compact ? 12 : 128, t: 12, b: 26 }
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b

  const dates = [...points.map(p => +new Date(p.date)), ...therapyStarts.map(t => +new Date(t.date))]
  let x0 = Math.min(...dates), x1 = Math.max(...dates)
  if (!isFinite(x0)) return <p className="muted">Анкет пока нет.</p>
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

  const label = scale === 'phq9' ? 'PHQ-9' : 'GAD-7'
  return (
    <figure className="chart" style={{ margin: 0 }} aria-label={`Динамика ${label}`}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img">
        <title>{`Динамика ${label}: ${scored.map(p => `${fmt(p.date)} — ${p.total}`).join(', ')}`}</title>
        {bands.map((b, i) => {
          const top = i < bands.length - 1 ? bands[i + 1].min : yMax
          return (
            <g key={b.label}>
              <rect x={pad.l} width={iw} y={y(top)} height={y(b.min) - y(top)} fill={BAND_FILL[i]} />
              {!compact && <text className="band-label" x={pad.l + iw + 8} y={(y(b.min) + y(top)) / 2 + 4}>{b.label}</text>}
              <text className="axis" x={pad.l - 6} y={y(b.min) + 4} textAnchor="end">{b.min}</text>
            </g>
          )
        })}
        <text className="axis" x={pad.l - 6} y={y(yMax) + 4} textAnchor="end">{yMax}</text>

        {therapyStarts.map(t => (
          <g key={t.date + t.label}>
            <line x1={x(t.date)} x2={x(t.date)} y1={pad.t} y2={pad.t + ih} stroke="var(--rx)" strokeWidth={1.5} />
            {!compact && <text className="axis" x={x(t.date) + 4} y={pad.t + 11} style={{ fill: 'var(--rx)' }}>{t.label}</text>}
          </g>
        ))}

        {segs.map(({ a, b, gap }, i) => (
          <line key={i} x1={x(a.date)} y1={y(a.total)} x2={x(b.date)} y2={y(b.total)}
            stroke={gap ? 'var(--ink-3)' : 'var(--ink)'} strokeWidth={2.25} strokeLinecap="round" strokeDasharray={gap ? '5 6' : undefined} />
        ))}
        {scored.map(p => (
          <g key={p.date + p.total}>
            <circle cx={x(p.date)} cy={y(p.total)} r={4.5}
              fill={p.prorated ? 'var(--surface)' : 'var(--ink)'} stroke="var(--ink)" strokeWidth={2} />
            {!compact && <text className="val" x={x(p.date)} y={y(p.total) - 10} textAnchor="middle">{p.total}</text>}
          </g>
        ))}
        {points.filter(p => p.total === null).map(p => (
          <g key={'na' + p.date}>
            <line x1={x(p.date)} x2={x(p.date)} y1={pad.t + ih - 10} y2={pad.t + ih} stroke="var(--ink-3)" strokeWidth={2} />
            {!compact && <text className="axis" x={x(p.date)} y={pad.t + ih - 14} textAnchor="middle">н/д</text>}
          </g>
        ))}
        {scored.map(p => (
          <text key={'x' + p.date} className="axis" x={x(p.date)} y={H - 8} textAnchor="middle">{fmt(p.date)}</text>
        ))}
      </svg>
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
