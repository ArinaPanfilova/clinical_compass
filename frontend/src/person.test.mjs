// Подпись пользователя в шапке. Запуск: node --test frontend/src/person.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { person } from './person.ts'

test('врач: ФИО сокращается до фамилии с инициалами, специальность — подпись', () => {
  assert.deepEqual(person({ display_name: 'Иванова Елена Андреевна, терапевт', role: 'doctor' }),
    { short: 'Иванова Е. А.', sub: 'терапевт', initials: 'ИЕ' })
})

test('пациент с коротким именем остаётся как есть, подпись — роль', () => {
  assert.deepEqual(person({ display_name: 'Анна К.', role: 'patient' }), { short: 'Анна К.', sub: 'пациент', initials: 'АК' })
})

test('пояснение в скобках — не отчество: уходит в подпись, имя не режется', () => {
  assert.deepEqual(person({ display_name: 'Исследователь (обезличенные данные)', role: 'researcher' }),
    { short: 'Исследователь', sub: 'обезличенные данные', initials: 'И' })
})

test('одно слово без пояснения: подпись — роль, инициал — первая буква', () => {
  assert.deepEqual(person({ display_name: 'Регистратура', role: 'doctor' }), { short: 'Регистратура', sub: 'врач', initials: 'Р' })
})
