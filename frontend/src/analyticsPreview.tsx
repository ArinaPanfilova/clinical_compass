// Стенд экрана аналитики: npx vite → /analytics-preview.html
// Источник «Макет» читает public/mock/analytics-*.json (только GAD-7, фильтры не применяются),
// «Сервер» — настоящий /api/analytics/aviandr (python -m server; вход демо-аккаунтом).
// Параметры в адресе (?role=researcher&theme=dark&source=mock&scenario=empty) — для повторяемых скриншотов.
import { StrictMode, useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/jost/400.css'
import '@fontsource/jost/500.css'
import '@fontsource/jost/600.css'
import '@fontsource/jost/700.css'
import './styles.css'
import { AnalyticsView } from './components/AnalyticsView'
import type { AnalyticsQuery, AviandrReport } from './analyticsTypes'

type Role = 'doctor' | 'researcher'
type Theme = 'system' | 'light' | 'dark'
type Source = 'mock' | 'server'
type Scenario = 'data' | 'empty' | 'suppressed' | 'error'

const CAVEAT = 'Наблюдение без контрольной группы. По изменению шкалы нельзя отделить эффект препарата ' +
  'от естественного течения болезни, регрессии к среднему и отбора пациентов.'
const LOGIN: Record<Role, string> = { doctor: 'ivanova', researcher: 'researcher' }
const tokens: Partial<Record<Role, string>> = {}
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))
const qs = (q: AnalyticsQuery) => new URLSearchParams(Object.entries(q) as [string, string][]).toString()

async function fromServer(role: Role, q: AnalyticsQuery): Promise<AviandrReport> {
  if (!tokens[role]) {
    const r = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login: LOGIN[role], password: 'demo' }),
    })
    if (!r.ok) throw new Error(`Вход не удался (${r.status}). Запущен ли python -m server?`)
    tokens[role] = (await r.json()).token
  }
  const r = await fetch(`/api/analytics/aviandr?${qs(q)}`, { headers: { Authorization: `Bearer ${tokens[role]}` } })
  if (!r.ok) throw new Error(`Сервер ответил ${r.status}`)
  return r.json()
}

async function fromMock(role: Role, scenario: Scenario, q: AnalyticsQuery): Promise<AviandrReport> {
  await sleep(350)
  const k = role === 'researcher' ? 5 : 1
  if (scenario === 'error') throw new Error('Сервер аналитики не ответил (имитация на стенде).')
  if (scenario === 'empty') return { k_min: k, scale: q.scale, caveat: CAVEAT, n: 0, empty: true, suppressed: false, synthetic: true }
  if (scenario === 'suppressed') {
    return { k_min: 5, scale: q.scale, caveat: CAVEAT, n: null, suppressed: true, synthetic: true,
      message: 'В выборке меньше 5 курсов. Показ скрыт, чтобы исключить повторную идентификацию.' }
  }
  const r = await fetch(`./mock/analytics-${role}.json`)
  if (!r.ok) throw new Error(`Нет файла mock/analytics-${role}.json`)
  return r.json()
}

function pick<T extends string>(p: URLSearchParams, key: string, allowed: readonly T[], fallback: T): T {
  const v = p.get(key) as T | null
  return v && allowed.includes(v) ? v : fallback
}

function Seg<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, t]) => <button key={v} aria-pressed={value === v} onClick={() => onChange(v)}>{t}</button>)}
    </div>
  )
}

function Stand() {
  const p = new URLSearchParams(location.search)
  const [role, setRole] = useState<Role>(pick<Role>(p, 'role', ['doctor', 'researcher'], 'doctor'))
  const [theme, setTheme] = useState<Theme>(pick<Theme>(p, 'theme', ['system', 'light', 'dark'], 'system'))
  const [source, setSource] = useState<Source>(pick<Source>(p, 'source', ['mock', 'server'], 'mock'))
  const [scenario, setScenario] = useState<Scenario>(pick<Scenario>(p, 'scenario', ['data', 'empty', 'suppressed', 'error'], 'data'))
  const [last, setLast] = useState('')

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') delete root.dataset.theme
    else root.dataset.theme = theme
    history.replaceState(null, '', `?${new URLSearchParams({ role, theme, source, scenario })}`)
  }, [role, theme, source, scenario])

  const fetchReport = useCallback((q: AnalyticsQuery) => {
    setLast(qs(q))
    return source === 'server' ? fromServer(role, q) : fromMock(role, scenario, q)
  }, [role, source, scenario])

  return (
    <>
      <header className="topbar stand-bar">
        <span className="logo">Компас · стенд аналитики</span>
        <Seg label="Роль" value={role} onChange={setRole} options={[['doctor', 'Врач'], ['researcher', 'Исследователь']]} />
        <Seg label="Тема" value={theme} onChange={setTheme} options={[['system', 'Системная'], ['light', 'Светлая'], ['dark', 'Тёмная']]} />
        <Seg label="Источник" value={source} onChange={setSource} options={[['mock', 'Макет'], ['server', 'Сервер']]} />
        {source === 'mock' && (
          <Seg label="Сценарий" value={scenario} onChange={setScenario}
            options={[['data', 'Данные'], ['empty', 'Пусто'], ['suppressed', 'Скрыто'], ['error', 'Ошибка']]} />
        )}
        <span className="stand-q" title="Последний запрос fetchReport">{last && `fetchReport(${decodeURIComponent(last)})`}</span>
      </header>
      <AnalyticsView key={`${source}-${scenario}`} role={role} fetchReport={fetchReport} />
    </>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><Stand /></StrictMode>)
