import { useMemo, useState } from 'react'
import type { Mode } from '../api'
import { ALL_SAFETY_KEYS, DRUG_STATUS, FACT_LABELS, SAFETY_LABELS } from '../content'
import type { Alert, Change, Decision, Finding, PatientBundle, ScalePoint, User } from '../types'
import { api } from '../api'
import { plural } from './analytics/model'
import { DocumentDialog } from './DocumentDialog'
import { FindingItem } from './FindingItem'
import { MessagesPanel } from './MessagesPanel'
import { TrendChart } from './TrendChart'

// Рабочее место врача — три панели во всю высоту экрана:
// список пациентов | карточка (шапка, показатели, «Требует решения», динамика, дневник, журнал) |
// «Терапия и безопасность» (препарат, профиль безопасности, наблюдение на терапии) и «Сообщения».
// Каждая панель прокручивается сама; на узком экране панели складываются в одну колонку.

const RANK: Record<string, number> = { emergency: 0, urgent: 1, planned: 2, info: 3, none: 4 }

interface Props {
  patients: PatientBundle[]
  mode: Mode
  user: User
  selected: string | null
  onSelect: (pid: string) => void
  onDecide: (pid: string, f: Finding, action: Decision['action'], comment?: string) => Promise<void>
  onAlertAction: (pid: string, alertId: string, action: 'accept') => Promise<void>
  onReplace: (b: PatientBundle) => void
  msgTick: number
}

export const shortName = (n: string) => n.replace(/\s*\(синт\.\)/, '')
const initials = (n: string) => shortName(n).split(' ').map(w => w[0]).join('').slice(0, 2)
const day = (d: string) => new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
// Ключи фактов в тексте причин («safety.pregnancy») — человеческими словами из FACT_LABELS
const FACT_RE = /\b(?:safety|diagnosis|patient|context)\.[a-z0-9_]+/g
const humanize = (s: string) => s.replace(FACT_RE, m => FACT_LABELS[m] ?? m)
const factsWord = (n: number) => `${n} ${plural(n, 'факт', 'факта', 'фактов')}`
/** Причина «не хватает данных: a, b, c…» повторяет список «Уточните у пациента» — показываем её коротко. */
function reasonText(x: string, unknown: string[]) {
  const keys = x.match(FACT_RE) ?? []
  if (keys.length > 2 && x.includes(':') && keys.every(k => unknown.includes(k))) return `${x.slice(0, x.indexOf(':'))}: ${factsWord(keys.length)}, список ниже`
  return humanize(x)
}

function toneOf(b: PatientBundle): 'must' | 'want' | 'calm' {
  const t = b.evaluation.triage_level
  const mandatory = b.evaluation.findings.some(f => f.routing === 'mandatory')
  return t === 'emergency' || (t === 'urgent' && mandatory) ? 'must' : t === 'urgent' ? 'want' : 'calm'
}

export function DoctorView({ patients, mode, user, selected, onSelect, onDecide, onAlertAction, onReplace, msgTick }: Props) {
  const sorted = useMemo(() => [...patients].sort((a, b) => {
    const r = RANK[a.evaluation.triage_level] - RANK[b.evaluation.triage_level]
    if (r) return r
    const ma = a.evaluation.findings.some(f => f.routing === 'mandatory') ? 0 : 1
    const mb = b.evaluation.findings.some(f => f.routing === 'mandatory') ? 0 : 1
    return ma - mb || a.record.name.localeCompare(b.record.name)
  }), [patients])
  const [q, setQ] = useState('')
  const p = patients.find(x => x.record.patient_id === selected) ?? sorted[0]
  const visible = sorted.filter(x => x.record.name.toLowerCase().includes(q.trim().toLowerCase()))

  const groups = [
    { title: 'Требуют реакции сегодня', items: visible.filter(x => RANK[x.evaluation.triage_level] <= 1) },
    { title: 'Плановое наблюдение', items: visible.filter(x => RANK[x.evaluation.triage_level] > 1) },
  ].filter(g => g.items.length)

  return (
    <div className="doctor">
      <nav className="roster" aria-label="Пациенты">
        <div className="roster-top">
          <h2>Мои пациенты <span className="count">{patients.length}</span></h2>
          <input className="search" type="search" placeholder="Найти по имени" aria-label="Найти пациента"
            value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <div className="roster-list">
          {groups.map(g => (
            <div key={g.title} className="roster-section">
              <div className="roster-group">{g.title}<span>{g.items.length}</span></div>
              {g.items.map(x => <RosterItem key={x.record.patient_id} b={x} current={x === p} onClick={() => onSelect(x.record.patient_id)} />)}
            </div>
          ))}
          {groups.length === 0 && <p className="roster-empty">Никого не нашли. Проверьте написание имени.</p>}
        </div>
      </nav>
      {p && <PatientCard key={p.record.patient_id} b={p} mode={mode} user={user} onDecide={onDecide}
        onAlertAction={onAlertAction} onReplace={onReplace} msgTick={msgTick} />}
    </div>
  )
}

function last(b: PatientBundle, s: 'phq9' | 'gad7'): ScalePoint | null {
  const pts = b.evaluation.details.scales[s] ?? []
  return pts.length ? pts[pts.length - 1] : null
}

function RosterItem({ b, current, onClick }: { b: PatientBundle; current: boolean; onClick: () => void }) {
  const t = b.evaluation.triage_level
  const mandatory = b.evaluation.findings.some(f => f.routing === 'mandatory')
  const tone = toneOf(b)
  const main = last(b, b.record.primary_scale)
  const ch = b.evaluation.details.changes[b.record.primary_scale]
  const stale = b.record.selfreports_missed_consecutive >= 2
  const reason = t === 'emergency' ? 'Экстренный сигнал'
    : mandatory ? 'Обязательно к психиатру'
    : stale ? 'Нет свежих анкет'
    : b.evaluation.findings.length ? `${b.evaluation.findings.length} на рассмотрении` : 'Без новых сигналов'
  return (
    <button className={`roster-item tone-${tone}`} aria-current={current} onClick={onClick}>
      <span className="avatar" aria-hidden>{initials(b.record.name)}</span>
      <span className="roster-text">
        <span className="who">{shortName(b.record.name)}{b.link === 'deputy' && <span className="chip-deputy">замещение</span>}</span>
        <span className="sub">{reason}</span>
      </span>
      <span className={`roster-score ${stale ? 'stale' : ''}`}>
        <span className="lbl">{b.record.primary_scale === 'phq9' ? 'PHQ-9' : 'GAD-7'}</span>
        <span className="val">{main?.total ?? '—'}
          {ch && ch.direction !== 'no_meaningful_change' && (
            <span className={`trend ${ch.direction}`} aria-label={ch.direction === 'worsened' ? 'ухудшение' : 'улучшение'}>{ch.direction === 'worsened' ? '▲' : '▼'}</span>
          )}
        </span>
      </span>
    </button>
  )
}

function ScaleStat({ name, p, ch, active, onClick }: { name: string; p: ScalePoint | null; ch?: Change; active: boolean; onClick: () => void }) {
  return (
    <button className="stat stat-btn" aria-pressed={active} onClick={onClick} title="Показать на графике">
      <span className="stat-label">{name}</span>
      <span className="stat-value">{p?.total ?? '—'}<small>{p?.category_label?.toLowerCase() ?? 'нет данных'}</small></span>
      <span className={`stat-delta ${ch?.direction ?? ''}`}>
        {ch ? `${ch.delta > 0 ? '+' : ''}${ch.delta} от исходного` : 'одно наблюдение'}
      </span>
    </button>
  )
}

interface CardProps {
  b: PatientBundle
  mode: Mode
  user: User
  onDecide: Props['onDecide']
  onAlertAction: Props['onAlertAction']
  onReplace: Props['onReplace']
  msgTick: number
}

type FactState = 'yes' | 'unk' | 'no'
const FACT_ORDER: Record<FactState, number> = { yes: 0, unk: 1, no: 2 }

function PatientCard({ b, mode, user, onDecide, onAlertAction, onReplace, msgTick }: CardProps) {
  const { record: r, evaluation: e } = b
  const [scale, setScale] = useState<'phq9' | 'gad7'>(r.primary_scale)
  const [err, setErr] = useState<string | null>(null)
  const [docOpen, setDocOpen] = useState(false)
  const decisions = b.decisions ?? []
  const alerts = b.alerts ?? []

  const guard = async (fn: () => Promise<void>) => {
    setErr(null)
    try { await fn() } catch (x) { setErr(String((x as Error).message)) }
  }
  const decide = (f: Finding, action: Decision['action'], comment?: string) => guard(() => onDecide(r.patient_id, f, action, comment))
  // Врач уточнил у пациента: факт профиля безопасности из «неизвестно» в «да»/«нет»
  const setFact = (k: string, v: boolean) => guard(async () => onReplace(await api.updateSafety(r.patient_id, { [k]: v }, 'manual')))
  const decisionFor = (f: Finding) => [...decisions].reverse().find(d => d.finding_rule_id === f.rule_id)
  const alertFor = (f: Finding): Alert | undefined => [...alerts].reverse().find(a => a.rule_id === f.rule_id)

  const main = e.findings.filter(f => f.kind !== 'data_quality' || f.priority === 'urgent')
  const dq = e.findings.filter(f => f.kind === 'data_quality' && f.priority !== 'urgent')
  const open = main.filter(f => !decisionFor(f)).length

  const sp = r.safety_profile ?? {}
  const state = (k: string): FactState => sp[k] === true ? 'yes' : sp[k] === false ? 'no' : 'unk'
  const filled = ALL_SAFETY_KEYS.filter(k => state(k) !== 'unk')
  const flagged = ALL_SAFETY_KEYS.filter(k => state(k) === 'yes')
  const unknown = ALL_SAFETY_KEYS.length - filled.length
  const facts = [...ALL_SAFETY_KEYS].sort((a, c) => FACT_ORDER[state(a)] - FACT_ORDER[state(c)])
  // Полный и чистый профиль свёрнут в одну строку; раскрытие запоминается до смены пациента
  const [spOpen, setSpOpen] = useState(flagged.length > 0 || unknown > 0)
  const spTone = flagged.length ? 'rx' : unknown ? 'want' : 'ok'
  const spSummary = flagged.length
    ? `Факторы риска: ${flagged.length}${unknown ? ` · нет данных: ${unknown}` : ''}`
    : unknown ? `Нет данных: ${unknown} из ${ALL_SAFETY_KEYS.length}` : `${ALL_SAFETY_KEYS.length} из ${ALL_SAFETY_KEYS.length} · ограничений нет`

  const ch = e.details.changes[scale]
  const trend = e.details.trends[scale]
  const therapyStarts = r.therapy.current.filter(t => t.start_date).map(t => ({ date: t.start_date!, label: t.mnn.split(' ')[0] }))
  const drug = e.drug_checks[0]
  const unkSafety = drug ? drug.unknown_facts.filter(f => f.startsWith('safety.')) : []
  const unkOther = drug ? drug.unknown_facts.filter(f => !f.startsWith('safety.')) : []
  const adh = r.adherence
  const adhTotal = adh ? adh.confirmed + adh.missed + adh.unknown : 0
  const tone = toneOf(b)

  return (
    <>
      <main className="card" aria-labelledby="pt-name">
        <header className="head">
          <span className={`avatar lg tone-${tone}`} aria-hidden>{initials(r.name)}</span>
          <div className="head-text">
            <h1 id="pt-name">{shortName(r.name)}</h1>
            <p className="meta">
              <span>{r.age} лет, {r.sex === 'Ж' ? 'женщина' : 'мужчина'}</span>
              {r.diagnoses.map(d => (
                <span key={d.code} className="dx">
                  <b>{d.code}</b> {d.label}{d.status !== 'confirmed' && <em> предварительный</em>}
                </span>
              ))}
              {r.diagnoses.length === 0 && <span className="dx">диагноз не установлен</span>}
            </p>
          </div>
          <span className="synthetic" title={r.scenario}>Синтетический профиль</span>
        </header>
        <p className="scenario">{r.scenario}</p>
        {b.link === 'deputy' && (
          <p className="warn-line must">Замещение: пациент лечащего врача, сигнал не принят вовремя и передан вам ({user.display_name}). Доступ открыт только на время работы с этим сигналом.</p>
        )}

        <div className="stats">
          <ScaleStat name="PHQ-9 · депрессия" p={last(b, 'phq9')} ch={e.details.changes.phq9} active={scale === 'phq9'} onClick={() => setScale('phq9')} />
          <ScaleStat name="GAD-7 · тревога" p={last(b, 'gad7')} ch={e.details.changes.gad7} active={scale === 'gad7'} onClick={() => setScale('gad7')} />
          <div className="stat">
            <span className="stat-label">Терапия</span>
            <span className="stat-text">{r.therapy.current.length ? r.therapy.current.map(t => t.mnn.split(' (')[0]).join(', ') : 'не назначена'}</span>
            <span className="stat-delta">
              {r.therapy.weeks_on_current ? `${r.therapy.weeks_on_current} нед.` : ''}
              {adh ? `${r.therapy.weeks_on_current ? ', ' : ''}отмечено ${Math.round((adh.confirmed / adhTotal) * 100)}% приёмов` : ''}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Профиль безопасности</span>
            <span className="stat-text">
              {filled.length}<span className="of"> из {ALL_SAFETY_KEYS.length}</span>
            </span>
            <span className={`stat-delta ${flagged.length ? 'flagged' : unknown ? 'unknown' : ''}`}>
              {flagged.length ? flagged.map(k => SAFETY_LABELS[k]).join(', ') : unknown ? 'есть пробелы' : 'ограничений нет'}
            </span>
          </div>
        </div>

        <section className="attention" aria-labelledby="att">
          <div className="section-head">
            <h2 id="att">Требует решения {open > 0 && <span className="count">{open}</span>}</h2>
            <span className="faint">Клинические действия выполняет только врач</span>
          </div>
          {err && <p className="warn-line">{err}</p>}
          {main.length === 0 && <p className="empty">Новых сигналов нет. Это не означает отсутствие опасности: данные могли не поступить.</p>}
          <div className="findings">
            {main.map(f => (
              <FindingItem key={f.rule_id} f={f} decision={decisionFor(f)} onDecide={(a, c) => decide(f, a, c)}
                alert={alertFor(f)} onAccept={mode === 'live' ? (id => guard(() => onAlertAction(r.patient_id, id, 'accept'))) : undefined} />
            ))}
          </div>
          {/* МЕСТО для блока «Направление к психиатру»: section.panel здесь, сразу под находками —
              основание (маршрутизация «обязательно / желательно») и оформление направления рядом. */}
          {dq.length > 0 && (
            <details className="dq-group">
              <summary>Качество данных и справочные отметки ({dq.length})</summary>
              <div className="findings">
                {dq.map(f => <FindingItem key={f.rule_id} f={f} decision={decisionFor(f)} onDecide={(a, c) => decide(f, a, c)} />)}
              </div>
            </details>
          )}
        </section>

        <div className="card-grid">
          <section className="panel chart-panel" aria-labelledby="dyn-h">
            <div className="panel-head">
              <h2 id="dyn-h">Динамика</h2>
              <div className="seg" role="group" aria-label="Шкала">
                {(['phq9', 'gad7'] as const).map(s => (
                  <button key={s} aria-pressed={scale === s} onClick={() => setScale(s)}>{s === 'phq9' ? 'PHQ-9' : 'GAD-7'}</button>
                ))}
              </div>
            </div>
            <TrendChart scale={scale} points={e.details.scales[scale] ?? []} therapyStarts={therapyStarts} />
            {ch ? (
              <p className="change-line">
                <strong className={ch.direction}>{ch.direction === 'worsened' ? 'Клинически значимое ухудшение' : ch.direction === 'improved' ? 'Клинически значимое улучшение' : 'Изменение меньше порога значимости'}</strong>
                {' '}({ch.baseline} → {ch.current}, порог {ch.thresholds.mcid}).
                {ch.response && ' Снижение на 50% и больше.'}{ch.remission && ' Ниже порога ремиссии по шкале.'}
                <span className="faint">Порог — популяционный ориентир. Изменение описывает ряд наблюдений и само по себе не доказывает эффект лечения.</span>
              </p>
            ) : <p className="change-line faint">Для оценки изменения нужно минимум два рассчитанных наблюдения.</p>}
            {trend && trend.coverage < 0.7 && <p className="warn-line">Полнота наблюдения {Math.round(trend.coverage * 100)}% — стабильность не предполагается.</p>}
          </section>

          <section className="panel diary-panel" aria-labelledby="diary-h">
            <div className="panel-head"><h2 id="diary-h">Дневник пациента</h2><span className="faint">все записи целиком</span></div>
            {r.diary.length === 0 && <p className="empty">Пациент пока ничего не писал.</p>}
            {r.diary.map((d, i) => {
              const t = e.details.text[i]
              return (
                <div key={i} className={`diary-entry ${t?.flagged ? 'flag' : ''}`}>
                  <span className="diary-date">{day(d.date)}</span>
                  <p>{d.text}</p>
                  {t?.flagged && <p className="faint">Найдено: <mark>{t.matched.join(', ')}</mark>. Поиск по словарю неполон — читайте все записи.</p>}
                </div>
              )
            })}
          </section>

          <section className="panel log-panel" aria-labelledby="log-h">
            <div className="panel-head"><h2 id="log-h">Журнал решений</h2>{decisions.length > 0 && <span className="count">{decisions.length}</span>}</div>
            {decisions.length === 0 ? <p className="empty">Решения появятся здесь после подтверждения или отклонения.</p> : (
              <ul className="log">
                {decisions.map((d, i) => (
                  <li key={i}>
                    <span className="faint">{new Date(d.at).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
                    <span>{ACTION[d.action]} {d.finding_rule_id}{d.comment ? `: «${d.comment}»` : ''}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <p className="disclaimer">{e.disclaimer} Ядро правил v{e.engine_version}, расчёт {e.elapsed_ms.toFixed(1)} мс.</p>
      </main>

      <aside className="rail" aria-label="Терапия, безопасность и сообщения">
        <div className="rail-group" role="group" aria-labelledby="rail-h">
          <h2 className="eyebrow" id="rail-h">Терапия и безопасность</h2>

          {drug && (
            <section className="panel drug-panel">
              <div className="panel-head">
                <h3>Авиандр</h3>
                <span className={`status-pill ${DRUG_STATUS[drug.status].tone}`}>{DRUG_STATUS[drug.status].label}</span>
              </div>
              <ul className="list">{drug.reasons.map(x => <li key={x}>{reasonText(x, drug.unknown_facts)}</li>)}</ul>
              {drug.unknown_facts.length > 0 && (
                <div className="sub-block">
                  <h4>Уточните у пациента</h4>
                  {unkOther.length > 0 && <ul className="fact-tags">{unkOther.map(x => <li key={x}>{FACT_LABELS[x] ?? x}</li>)}</ul>}
                  {/* факты профиля безопасности не повторяем: они ниже, с кнопками «да / нет» */}
                  {unkSafety.length > 0 && <p className="fact-more">{unkOther.length ? 'И ещё ' : ''}{factsWord(unkSafety.length)} профиля безопасности — отметьте в блоке ниже</p>}
                </div>
              )}
              {drug.cautions.length > 0 && <div className="sub-block"><h4>С осторожностью</h4><ul className="list">{drug.cautions.map(x => <li key={x}>{x}</li>)}</ul></div>}
              {drug.interactions.length > 0 && <div className="sub-block"><h4>Взаимодействия</h4><ul className="list">{drug.interactions.map(x => <li key={x}>{x}</li>)}</ul></div>}
              {e.findings.some(f => f.kind === 'alert' && !decisionFor(f)) && (
                <p className="warn-line must">Есть открытый сигнал безопасности: вопросы терапии — после оценки врачом.</p>
              )}
              {drug.warnings.map(w => <p key={w} className="warn-line">{w}</p>)}
              <p className="faint source">{drug.source}. Система не назначает препарат и не рассчитывает дозу: решение и его обоснование вносит врач.</p>
            </section>
          )}
          {/* МЕСТО для блока «Варианты терапии»: section.panel здесь, сразу под карточкой препарата —
              сравнение вариантов опирается на её статус и на профиль безопасности ниже. */}

          <section className="panel sp-panel">
            <div className="sp-body">
            <div className="panel-head">
              <h3>Профиль безопасности</h3>
              {mode === 'live' && (
                <button className="btn doc-btn" onClick={() => setDocOpen(true)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M12 18v-6M9.5 14.5 12 12l2.5 2.5" /></svg>
                  Загрузить документ
                </button>
              )}
            </div>
            <details className="sp-details" open={spOpen} onToggle={ev => setSpOpen(ev.currentTarget.open)}>
              <summary className="sp-summary">
                <span className={`sp-state tone-${spTone}`}>
                  <span className="sp-icon" aria-hidden />
                  {spSummary}
                </span>
                <span className="sp-more"><span className="sp-more-lbl">{spOpen ? 'Свернуть' : 'Все факты'}</span></span>
              </summary>
              <ul className="sp-chips">
                {facts.map(k => {
                  const s = state(k)
                  return (
                    <li key={k} className={`sp-chip v-${s}`}>
                      <span className="sp-label">{SAFETY_LABELS[k]}</span>
                      {s === 'unk' && mode === 'live' ? (
                        <span className="sp-ask">
                          <span className="sr-only">нет данных</span>
                          <button className="mini" aria-label={`${SAFETY_LABELS[k]}: да`} onClick={() => setFact(k, true)}>да</button>
                          <button className="mini" aria-label={`${SAFETY_LABELS[k]}: нет`} onClick={() => setFact(k, false)}>нет</button>
                        </span>
                      ) : (
                        <span className="sp-v">{s === 'yes' ? 'да' : s === 'no' ? 'нет' : 'нет данных'}</span>
                      )}
                    </li>
                  )
                })}
              </ul>
              {unknown > 0 && mode === 'live' && <p className="faint source">«Нет данных» — уточните у пациента или загрузите документ. Неизвестное не считается отсутствием противопоказания.</p>}
            </details>
            </div>
          </section>

          <section className="panel obs-panel">
            <div className="panel-head"><h3>На фоне терапии</h3><span className="faint">со слов пациента</span></div>
            {adh && (
              <>
                <h4 className="sub-h">Приём препарата</h4>
                <div className="adh">
                  <div><b>{adh.confirmed}</b><span>принял</span></div>
                  <div><b>{adh.missed}</b><span>пропустил</span></div>
                  <div><b className="unk">{adh.unknown}</b><span>без отметки</span></div>
                </div>
                <p className="faint note">Отметка не доказывает приём, её отсутствие — не пропуск.</p>
              </>
            )}
            <h4 className="sub-h">Нежелательные явления</h4>
            {r.adverse_events.length === 0 ? <p className="empty">Пациент не сообщал.</p> : (
              <ul className="list">
                {r.adverse_events.map((a, i) => (
                  <li key={i}>{day(a.date)}: {a.description}{a.serious ? ' (серьёзное)' : ''}</li>
                ))}
              </ul>
            )}
            <p className="faint note">Возникло на фоне лечения ≠ вызвано лечением.</p>
          </section>
        </div>

        <section className="panel msg-panel" aria-labelledby="msg-h">
          <div className="panel-head"><h2 id="msg-h">Сообщения</h2><span className="faint">не канал экстренной помощи</span></div>
          <MessagesPanel pid={r.patient_id} mode={mode} role="doctor" tick={msgTick} />
        </section>
      </aside>

      {docOpen && <DocumentDialog pid={r.patient_id} onClose={() => setDocOpen(false)} onApplied={onReplace} />}
    </>
  )
}

const ACTION: Record<string, string> = { confirm: 'Подтверждено', reject: 'Отклонено', modify: 'Изменено' }
