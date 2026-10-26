import { useMemo, useState } from 'react'
import type { Mode } from '../api'
import { ALL_SAFETY_KEYS, DRUG_STATUS, FACT_LABELS, SAFETY_LABELS } from '../content'
import type { Alert, Change, Decision, Finding, PatientBundle, ScalePoint, User } from '../types'
import { api } from '../api'
import { DocumentDialog } from './DocumentDialog'
import { FindingItem } from './FindingItem'
import { MessagesPanel } from './MessagesPanel'
import { TrendChart } from './TrendChart'

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
        {groups.map(g => (
          <div key={g.title} className="roster-section">
            <div className="roster-group">{g.title}<span>{g.items.length}</span></div>
            {g.items.map(x => <RosterItem key={x.record.patient_id} b={x} current={x === p} onClick={() => onSelect(x.record.patient_id)} />)}
          </div>
        ))}
        {groups.length === 0 && <p className="roster-empty">Никого не нашли. Проверьте написание имени.</p>}
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
  const tone = t === 'emergency' || (t === 'urgent' && mandatory) ? 'must' : t === 'urgent' ? 'want' : 'calm'
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
  const filled = ALL_SAFETY_KEYS.filter(k => sp[k] !== undefined && sp[k] !== null)
  const flagged = ALL_SAFETY_KEYS.filter(k => sp[k] === true)
  const ch = e.details.changes[scale]
  const trend = e.details.trends[scale]
  const therapyStarts = r.therapy.current.filter(t => t.start_date).map(t => ({ date: t.start_date!, label: t.mnn.split(' ')[0] }))
  const drug = e.drug_checks[0]
  const myDecisions = decisions
  const adh = r.adherence
  const adhTotal = adh ? adh.confirmed + adh.missed + adh.unknown : 0

  return (
    <main className="card">
      <header className="head">
        <span className="avatar lg" aria-hidden>{initials(r.name)}</span>
        <div className="head-text">
          <h1>{shortName(r.name)}</h1>
          <p className="meta">
            {r.age} лет, {r.sex === 'Ж' ? 'женщина' : 'мужчина'}
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
          <span className={`stat-delta ${flagged.length ? 'worsened' : filled.length < ALL_SAFETY_KEYS.length ? 'unknown' : ''}`}>
            {flagged.length ? flagged.map(k => SAFETY_LABELS[k]).join(', ') : filled.length < ALL_SAFETY_KEYS.length ? 'есть пробелы' : 'ограничений нет'}
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
        {dq.length > 0 && (
          <details className="dq-group">
            <summary>Качество данных и справочные отметки ({dq.length})</summary>
            <div className="findings">
              {dq.map(f => <FindingItem key={f.rule_id} f={f} decision={decisionFor(f)} onDecide={(a, c) => decide(f, a, c)} />)}
            </div>
          </details>
        )}
      </section>

      <div className="grid2">
        <div className="col">
          <section className="panel">
            <div className="panel-head">
              <h2>Динамика</h2>
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

          <section className="panel">
            <div className="panel-head"><h2>Дневник пациента</h2><span className="faint">все записи целиком</span></div>
            {r.diary.length === 0 && <p className="empty">Пациент пока ничего не писал.</p>}
            {r.diary.map((d, i) => {
              const t = e.details.text[i]
              return (
                <div key={i} className={`diary-entry ${t?.flagged ? 'flag' : ''}`}>
                  <span className="diary-date">{new Date(d.date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}</span>
                  <p>{d.text}</p>
                  {t?.flagged && <p className="faint">Найдено: <mark>{t.matched.join(', ')}</mark>. Поиск по словарю неполон — читайте все записи.</p>}
                </div>
              )
            })}
          </section>
        </div>

        <div className="col">
          <section className="panel">
            <div className="panel-head"><h2>Сообщения</h2><span className="faint">не канал экстренной помощи</span></div>
            <MessagesPanel pid={r.patient_id} mode={mode} role="doctor" tick={msgTick} />
          </section>

          {drug && (
            <section className="panel">
              <div className="panel-head"><h2>Авиандр</h2><span className={`status-pill ${DRUG_STATUS[drug.status].tone}`}>{DRUG_STATUS[drug.status].label}</span></div>
              <ul className="list">{drug.reasons.map(x => <li key={x}>{x}</li>)}</ul>
              {drug.unknown_facts.length > 0 && (
                <div className="sub-block"><h3>Уточните у пациента</h3><ul className="list">{drug.unknown_facts.map(x => <li key={x}>{FACT_LABELS[x] ?? x}</li>)}</ul></div>
              )}
              {drug.cautions.length > 0 && <div className="sub-block"><h3>С осторожностью</h3><ul className="list">{drug.cautions.map(x => <li key={x}>{x}</li>)}</ul></div>}
              {drug.interactions.length > 0 && <div className="sub-block"><h3>Взаимодействия</h3><ul className="list">{drug.interactions.map(x => <li key={x}>{x}</li>)}</ul></div>}
              {e.findings.some(f => f.kind === 'alert' && !decisionFor(f)) && (
                <p className="warn-line must">Есть открытый сигнал безопасности: вопросы терапии — после оценки врачом.</p>
              )}
              {drug.warnings.map(w => <p key={w} className="warn-line">{w}</p>)}
              <p className="faint source">{drug.source}. Система не назначает препарат и не рассчитывает дозу: решение и его обоснование вносит врач.</p>
            </section>
          )}

          <section className="panel">
            <div className="panel-head">
              <h2>Профиль безопасности</h2>
              <span className="faint">{filled.length} из {ALL_SAFETY_KEYS.length}</span>
              {mode === 'live' && <button className="btn" onClick={() => setDocOpen(true)}>Загрузить документ</button>}
            </div>
            <ul className="sp-list">
              {ALL_SAFETY_KEYS.map(k => {
                const v = sp[k]
                const unknown = v === undefined || v === null
                return (
                  <li key={k}>
                    <span>{SAFETY_LABELS[k]}</span>
                    {unknown && mode === 'live' ? (
                      <span className="sp-ask">
                        <span className="v-unk">нет данных</span>
                        <button className="mini" aria-label={`${SAFETY_LABELS[k]}: да`} onClick={() => setFact(k, true)}>да</button>
                        <button className="mini" aria-label={`${SAFETY_LABELS[k]}: нет`} onClick={() => setFact(k, false)}>нет</button>
                      </span>
                    ) : (
                      <span className={v === true ? 'v-yes' : v === false ? 'v-no' : 'v-unk'}>{v === true ? 'да' : v === false ? 'нет' : 'нет данных'}</span>
                    )}
                  </li>
                )
              })}
            </ul>
            {filled.length < ALL_SAFETY_KEYS.length && mode === 'live' && <p className="faint source">«Нет данных» — уточните у пациента или загрузите документ. Неизвестное не считается отсутствием противопоказания.</p>}
          </section>

          <section className="panel">
            <div className="panel-head"><h2>Нежелательные явления</h2></div>
            {r.adverse_events.length === 0 ? <p className="empty">Пациент не сообщал.</p> : (
              <ul className="list">
                {r.adverse_events.map((a, i) => (
                  <li key={i}>{new Date(a.date).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}: {a.description}{a.serious ? ' (серьёзное)' : ''}</li>
                ))}
              </ul>
            )}
            <p className="faint source">Возникло на фоне лечения ≠ вызвано лечением.</p>
          </section>

          {adh && (
            <section className="panel">
              <div className="panel-head"><h2>Приверженность</h2><span className="faint">по отметкам пациента</span></div>
              <div className="adh">
                <div><b>{adh.confirmed}</b><span>принял</span></div>
                <div><b>{adh.missed}</b><span>пропустил</span></div>
                <div><b className="unk">{adh.unknown}</b><span>без отметки</span></div>
              </div>
              <p className="faint source">Отметка не доказывает приём, её отсутствие — не пропуск.</p>
            </section>
          )}

          <section className="panel">
            <div className="panel-head"><h2>Журнал решений</h2></div>
            {myDecisions.length === 0 ? <p className="empty">Решения появятся здесь после подтверждения или отклонения.</p> : (
              <ul className="log">
                {myDecisions.map((d, i) => (
                  <li key={i}>
                    <span className="faint">{new Date(d.at).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
                    <span>{ACTION[d.action]} {d.finding_rule_id}{d.comment ? `: «${d.comment}»` : ''}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      {docOpen && <DocumentDialog pid={r.patient_id} onClose={() => setDocOpen(false)} onApplied={onReplace} />}
      <p className="disclaimer">{e.disclaimer} Ядро правил v{e.engine_version}, расчёт {e.elapsed_ms.toFixed(1)} мс.</p>
    </main>
  )
}

const ACTION: Record<string, string> = { confirm: 'Подтверждено', reject: 'Отклонено', modify: 'Изменено' }
