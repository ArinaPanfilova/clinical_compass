// Мелкие общие части экрана аналитики: число со скрытием «<k», строка доли с ДИ, горизонтальные столбики.
import type { CSSProperties, ReactNode } from 'react'
import type { MaskedCount, Rate } from '../../analyticsTypes'
import { useCountUp } from '../../hooks'
import { barFraction, ci, count, hiddenHint, num, pct } from './model'

/** Число плавно досчитывает до значения (KPI). format получает промежуточное значение. */
export function CountUp({ value, format }: { value: number; format: (v: number) => string }) {
  return <>{format(useCountUp(value))}</>
}
const whole = (v: number) => num(Math.round(v))

/** Счётчик: скрытая ячейка показывается как «<k» с подсказкой. */
export function Num({ v, k, className = '', animate }: { v: MaskedCount | undefined; k: number; className?: string; animate?: boolean }) {
  const c = count(v, k)
  if (!c.hidden) return <span className={className}>{animate && typeof v === 'number' ? <CountUp value={v} format={whole} /> : c.text}</span>
  return <span className={`an-hidden ${className}`} title={hiddenHint(k)} aria-label={`меньше ${k}: ${hiddenHint(k)}`}>{c.text}</span>
}

/** Доля с 95 % ДИ: подпись, определение, значение, «x из N» и отрезок ДИ на шкале 0–100 %. */
export function RateRow({ label, def, rate, denom, k, tone }: {
  label: string; def?: string; rate: Rate; denom: number; k: number; tone: 'brand' | 'rx'
}) {
  const hidden = Boolean(rate.hidden) || (rate.n === null && k > 1)
  const [lo, hi] = rate.ci95 ?? [0, 0]
  return (
    <div className={`an-rate tone-${tone}`}>
      <div className="an-rate-text">
        <span className="an-rate-label">{label}</span>
        {def && <span className="an-rate-def">{def}</span>}
      </div>
      <div className="an-rate-fig">
        {hidden
          ? <span className="an-rate-val an-hidden" title={hiddenHint(k)}>{`<${k}`}</span>
          : <span className="an-rate-val">{pct(rate.pct)}</span>}
        {!hidden && <span className="an-rate-n">{rate.n === null ? 'нет данных' : `${num(rate.n)} из ${num(denom)}`}</span>}
      </div>
      <div className="an-ci-track" aria-hidden>
        {!hidden && rate.ci95 && <span className="an-ci-range" style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />}
        {!hidden && rate.pct !== null && <span className="an-ci-dot" style={{ left: `${rate.pct}%` }} />}
      </div>
      <span className={`an-rate-ci ${hidden ? 'hid' : ''}`}>{hidden ? hiddenHint(k) : rate.ci95 ? `95 % ДИ ${ci(rate.ci95)}` : ''}</span>
    </div>
  )
}

/** Подписи шкалы 0–100 % под строками долей: та же сетка, что у строки, поэтому совпадают с отрезками ДИ. */
export function CiAxis() {
  return (
    <div className="an-rate an-rate-axis" aria-hidden>
      <div className="an-ci-axis">
        <span style={{ left: '0%' }}>0</span><span style={{ left: '50%' }}>50</span><span style={{ left: '100%' }}>100 %</span>
      </div>
    </div>
  )
}

export interface BarItem { key: string; label: ReactNode; value: MaskedCount; color?: string; hint?: string }

/** Горизонтальные столбики: подпись, столбик от общей базовой линии, значение у конца столбика. */
export function BarList({ items, max, k, compact }: { items: BarItem[]; max: number; k: number; compact?: boolean }) {
  return (
    <ul className={`an-bars ${compact ? 'compact' : ''}`}>
      {items.map(it => {
        const { frac, hidden } = barFraction(it.value, max, k)
        const style = { '--f': frac, '--c': it.color ?? 'var(--an-bar)' } as CSSProperties
        return (
          <li key={it.key} title={it.hint}>
            <span className="an-bar-label">{it.label}</span>
            <span className="an-bar-track" style={style}>
              <span className={`an-bar ${hidden ? 'ghost' : ''} ${!hidden && !it.value ? 'zero' : ''}`} />
              <Num v={it.value} k={k} className="an-bar-val" />
            </span>
          </li>
        )
      })}
    </ul>
  )
}
