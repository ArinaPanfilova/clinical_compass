// Тесты чистой логики экрана аналитики. Запуск без зависимостей:
//   node --test frontend/src/components/analytics/model.test.mjs
// (Node ≥ 22.18 сам снимает типы с model.ts.)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  AGE_OPTIONS, SCALE_MAX, SCALE_TICKS, ageKey, barFraction, bandPath, ci, cleanQuery, count, coursesWord,
  hiddenWeeks, isFiltered, linePath, pct, reportKind, segments, setAge, stopReasonRows,
} from './model.ts'

const sp = s => s.replace(/[  ]/g, ' ')   // неразрывные пробелы → обычные, для читаемости ожиданий

test('count: число, скрытая ячейка «<k», отсутствие данных', () => {
  assert.deepEqual(count(5, 5), { text: '5', hidden: false })
  assert.deepEqual(count(0, 5), { text: '0', hidden: false })
  assert.deepEqual(count(null, 5), { text: '<5', hidden: true })
  assert.deepEqual(count(null, 1), { text: '—', hidden: false })   // у врача null — просто нет данных
  assert.deepEqual(count(undefined, 5), { text: '—', hidden: false })
  assert.equal(sp(count(1234, 1).text), '1 234')
})

test('pct и ci: русская запятая, пробел перед %, ДИ из долей', () => {
  assert.equal(sp(pct(27.5)), '27,5 %')
  assert.equal(sp(pct(12)), '12 %')
  assert.equal(sp(pct(0)), '0 %')
  assert.equal(pct(null), '—')
  assert.equal(sp(ci([0.161, 0.428])), '16,1–42,8 %')
  assert.equal(sp(ci([0, 0.088])), '0–8,8 %')
  assert.equal(ci(null), '')
})

test('coursesWord: склонение', () => {
  const cases = { 0: 'курсов', 1: 'курс', 2: 'курса', 4: 'курса', 5: 'курсов', 11: 'курсов', 12: 'курсов',
    14: 'курсов', 21: 'курс', 22: 'курса', 40: 'курсов', 111: 'курсов', 302: 'курса' }
  for (const [n, w] of Object.entries(cases)) assert.equal(sp(coursesWord(Number(n))), `${n} ${w}`)
})

test('возраст: группа ↔ age_min/age_max', () => {
  assert.deepEqual(AGE_OPTIONS.map(o => o.key), ['', '18-34', '35-49', '50-64', '65+'])
  const q = { scale: 'gad7', sex: 'Ж' }
  assert.deepEqual(setAge(q, '35-49'), { scale: 'gad7', sex: 'Ж', age_min: '35', age_max: '49' })
  const old = setAge(setAge(q, '18-34'), '65+')
  assert.deepEqual(old, { scale: 'gad7', sex: 'Ж', age_min: '65' })     // верхней границы нет
  assert.deepEqual(setAge(old, ''), { scale: 'gad7', sex: 'Ж' })
  assert.equal(ageKey(setAge(q, '50-64')), '50-64')
  assert.equal(ageKey(old), '65+')
  assert.equal(ageKey(q), '')
  assert.equal(ageKey({ scale: 'gad7', age_min: '20', age_max: '30' }), '')   // не из списка — «все»
})

test('cleanQuery: пустое и «all» убирает, «none» оставляет', () => {
  assert.deepEqual(
    cleanQuery({ scale: 'phq9', sex: '', indication: 'all', comorbidity: 'none', start_from: '2025-01-01', age_max: undefined }),
    { scale: 'phq9', comorbidity: 'none', start_from: '2025-01-01' })
})

test('isFiltered: шкала не считается фильтром', () => {
  assert.equal(isFiltered({ scale: 'phq9' }), false)
  assert.equal(isFiltered({ scale: 'gad7', sex: '' }), false)
  assert.equal(isFiltered({ scale: 'gad7', concomitant: 'none' }), true)
})

test('reportKind: скрыт, пуст, полный', () => {
  assert.equal(reportKind({ k_min: 5, scale: 'gad7', caveat: '', n: null, suppressed: true, message: 'm' }), 'suppressed')
  assert.equal(reportKind({ k_min: 1, scale: 'gad7', caveat: '', n: 0, empty: true, suppressed: false }), 'empty')
  assert.equal(reportKind({ k_min: 1, scale: 'gad7', caveat: '', n: 40, empty: false, suppressed: false }), 'full')
})

const P = (week, median, hidden = false) => hidden
  ? { week, n: null, median: null, q1: null, q3: null, hidden: true }
  : { week, n: 10, median, q1: median - 1, q3: median + 1, hidden: false }

test('segments: скрытая точка и пропущенная неделя рвут линию', () => {
  const weeks = s => s.map(r => r.map(p => p.week))
  assert.deepEqual(weeks(segments([P(0, 15), P(2, 13), P(4, 12)])), [[0, 2, 4]])
  assert.deepEqual(weeks(segments([P(0, 15), P(2, 0, true), P(4, 12), P(6, 11)])), [[0], [4, 6]])
  assert.deepEqual(weeks(segments([P(0, 15), P(4, 12)])), [[0], [4]])         // недели 2 нет — не соединяем
  assert.deepEqual(weeks(segments([P(0, 14), P(2, 12), P(4, 11), P(6, 7.5), P(8, 0, true), P(10, 0, true)])), [[0, 2, 4, 6]])
  assert.deepEqual(segments([]), [])
  assert.deepEqual(hiddenWeeks([P(0, 14), P(8, 0, true), P(10, 0, true)]), [8, 10])
})

test('linePath и bandPath: линия медианы и полоса Q1–Q3', () => {
  const x = w => w * 10, y = v => 100 - v
  const run = [P(0, 15), P(2, 13)]
  assert.equal(linePath(run, x, y), 'M0 85L20 87')
  // вперёд по Q3, назад по Q1, замкнуто
  assert.equal(bandPath(run, x, y), 'M0 84L20 86L20 88L0 86Z')
})

test('barFraction: доля от максимума; скрытое — призрачный отрезок до k−1', () => {
  assert.deepEqual(barFraction(10, 40, 5), { frac: 0.25, hidden: false })
  assert.deepEqual(barFraction(null, 40, 5), { frac: 0.1, hidden: true })
  assert.deepEqual(barFraction(0, 0, 1), { frac: 0, hidden: false })
  assert.deepEqual(barFraction(null, 2, 5), { frac: 1, hidden: true })      // не вылезает за 100 %
})

test('stopReasonRows: причины без «завершён», по убыванию, скрытые — между 0 и k', () => {
  const labels = { completed: 'Курс завершён', adverse_event: 'НЯ', inefficacy: 'Нет эффекта', improvement: 'Улучшение',
    switch: 'Смена', lost_to_followup: 'Потеря контакта' }
  const rows = stopReasonRows({ adverse_event: 12, inefficacy: null, improvement: 0, switch: 8, lost_to_followup: 14 }, labels, 5)
  assert.deepEqual(rows.map(r => r.key), ['lost_to_followup', 'adverse_event', 'switch', 'inefficacy', 'improvement'])
  assert.equal(rows[0].label, 'Потеря контакта')
  assert.equal(rows[3].value, null)
})

test('шкалы: полный диапазон оси и деления', () => {
  assert.equal(SCALE_MAX.gad7, 21)
  assert.equal(SCALE_MAX.phq9, 27)
  assert.deepEqual(SCALE_TICKS.gad7, [0, 5, 10, 15, 21])
  assert.deepEqual(SCALE_TICKS.phq9, [0, 5, 10, 15, 20, 27])
})
