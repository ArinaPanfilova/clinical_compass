// Чистая логика экрана аналитики: форматирование, фильтры, геометрия графиков.
// Без React и без значений из других модулей — тестируется прямо в Node (model.test.mjs).
import type {
  AnalyticsQuery, AviandrReport, Ci95, MaskedCount, ScaleId, StopReason, TrajectoryPoint,
} from '../../analyticsTypes'

/** Полный диапазон шкалы: ось Y всегда от 0 до максимума. */
export const SCALE_MAX: Record<ScaleId, number> = { gad7: 21, phq9: 27 }
/** Деления оси Y — границы клинических градаций и максимум. */
export const SCALE_TICKS: Record<ScaleId, number[]> = { gad7: [0, 5, 10, 15, 21], phq9: [0, 5, 10, 15, 20, 27] }
export const SCALE_NAME: Record<ScaleId, string> = { gad7: 'GAD-7', phq9: 'PHQ-9' }
/** Шаг визитов в неделях (kompas_core.analytics.WEEKS) */
export const WEEK_STEP = 2

const NBSP = ' '
const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

export const num = (x: number) => nf.format(x)
export const hiddenHint = (k: number) => `скрыто: меньше ${k} человек`

/** Счётчик для показа. null при k > 1 — скрытая ячейка «<k», иначе — нет данных. */
export function count(v: MaskedCount | undefined, k: number): { text: string; hidden: boolean } {
  if (v === null && k > 1) return { text: `<${k}`, hidden: true }
  if (v === null || v === undefined) return { text: '—', hidden: false }
  return { text: num(v), hidden: false }
}

export const pct = (p: number | null | undefined) => (p === null || p === undefined ? '—' : `${num(p)}${NBSP}%`)

/** 95 % ДИ приходит долями 0…1. */
export const ci = (c: Ci95 | null | undefined) =>
  c ? `${num(Math.round(c[0] * 1000) / 10)}–${num(Math.round(c[1] * 1000) / 10)}${NBSP}%` : ''

export function plural(n: number, one: string, few: string, many: string) {
  const a = Math.abs(n) % 100, b = a % 10
  if (a > 10 && a < 20) return many
  if (b === 1) return one
  if (b >= 2 && b <= 4) return few
  return many
}
export const coursesWord = (n: number) => `${num(n)}${NBSP}${plural(n, 'курс', 'курса', 'курсов')}`

/** Значение счётчика KPI через elapsed мс из ms: ease-out от a к b. Метка кадра бывает раньше старта —
 *  прогресс зажат в 0…1, поэтому число не выходит за [a, b]. */
export function countUp(a: number, b: number, elapsed: number, ms: number): number {
  const k = Math.min(1, Math.max(0, elapsed / ms))
  return a + (b - a) * (1 - (1 - k) ** 3)
}

// ---------- Фильтры ----------

export const AGE_OPTIONS: { key: string; label: string; min?: string; max?: string }[] = [
  { key: '', label: 'Все' },
  { key: '18-34', label: '18–34', min: '18', max: '34' },
  { key: '35-49', label: '35–49', min: '35', max: '49' },
  { key: '50-64', label: '50–64', min: '50', max: '64' },
  { key: '65+', label: '65+', min: '65' },
]

export function ageKey(q: AnalyticsQuery): string {
  const o = AGE_OPTIONS.find(o => o.key && o.min === q.age_min && o.max === q.age_max)
  return o?.key ?? ''
}

export function setAge(q: AnalyticsQuery, key: string): AnalyticsQuery {
  const { age_min: _a, age_max: _b, ...rest } = q
  const o = AGE_OPTIONS.find(o => o.key === key && o.key)
  if (!o) return rest
  return { ...rest, age_min: o.min, ...(o.max ? { age_max: o.max } : {}) }
}

/** Убирает «все» ('' / 'all' / undefined). 'none' — это фильтр «нет», он остаётся. */
export function cleanQuery(q: AnalyticsQuery): AnalyticsQuery {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== '' && v !== 'all') out[k] = v
  return out as unknown as AnalyticsQuery
}

export const isFiltered = (q: AnalyticsQuery) => Object.keys(cleanQuery(q)).some(k => k !== 'scale')

export function reportKind(r: AviandrReport): 'suppressed' | 'empty' | 'full' {
  if (r.suppressed) return 'suppressed'
  if (r.empty) return 'empty'
  return 'full'
}

// ---------- Траектории ----------

type Shown = TrajectoryPoint & { median: number; q1: number; q3: number }
const shown = (p: TrajectoryPoint): p is Shown => !p.hidden && p.median !== null && p.q1 !== null && p.q3 !== null

/** Непрерывные участки линии: скрытая точка или пропущенный визит дают разрыв. */
export function segments(points: TrajectoryPoint[]): Shown[][] {
  const runs: Shown[][] = []
  let prev: TrajectoryPoint | null = null
  for (const p of points) {
    if (shown(p)) {
      const cont = prev && shown(prev) && p.week - prev.week === WEEK_STEP
      if (cont) runs[runs.length - 1].push(p)
      else runs.push([p])
    }
    prev = p
  }
  return runs
}

export const hiddenWeeks = (points: TrajectoryPoint[]) => points.filter(p => p.hidden).map(p => p.week)

const r1 = (v: number) => Math.round(v * 10) / 10

export function linePath(run: TrajectoryPoint[], x: (w: number) => number, y: (v: number) => number): string {
  return run.filter(shown).map((p, i) => `${i ? 'L' : 'M'}${r1(x(p.week))} ${r1(y(p.median))}`).join('')
}

/** Полоса Q1–Q3: вперёд по Q3, назад по Q1. */
export function bandPath(run: TrajectoryPoint[], x: (w: number) => number, y: (v: number) => number): string {
  const pts = run.filter(shown)
  if (!pts.length) return ''
  const top = pts.map(p => `${r1(x(p.week))} ${r1(y(p.q3))}`)
  const bottom = [...pts].reverse().map(p => `${r1(x(p.week))} ${r1(y(p.q1))}`)
  return `M${[...top, ...bottom].join('L')}Z`
}

// ---------- Столбики ----------

/** Длина столбика от максимума. Скрытое значение — «призрак» до k−1: настоящее число где-то от 1 до k−1. */
export function barFraction(v: MaskedCount, max: number, k: number): { frac: number; hidden: boolean } {
  const hidden = v === null && k > 1
  const value = hidden ? k - 1 : v ?? 0
  if (max <= 0) return { frac: 0, hidden }
  return { frac: Math.min(1, value / max), hidden }
}

/** Ключ сортировки: скрытое значение (1…k−1) встаёт между 0 и k. */
export const sortValue = (v: MaskedCount, k: number) => (v === null ? (k > 1 ? k - 0.5 : -1) : v)

export function stopReasonRows(byReason: Partial<Record<string, MaskedCount>>, labels: Record<StopReason, string>, k: number) {
  const order = Object.keys(labels).filter(r => r !== 'completed') as Exclude<StopReason, 'completed'>[]
  return order
    .filter(key => key in byReason)
    .map(key => ({ key, label: labels[key], value: byReason[key] ?? null }))
    .sort((a, b) => sortValue(b.value, k) - sortValue(a.value, k))
}
