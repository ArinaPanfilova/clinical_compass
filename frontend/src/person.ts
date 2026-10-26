// Подпись пользователя в шапке: короткое имя, подпись под ним и инициалы для аватара.
import type { User } from './types'

export const ROLE_LABEL: Record<User['role'], string> = { doctor: 'врач', patient: 'пациент', researcher: 'исследователь' }

/** «Иванова Елена Андреевна, терапевт» → «Иванова Е. А.», подпись «терапевт», инициалы «ИЕ». */
export function person(u: Pick<User, 'display_name' | 'role'>) {
  const [full, spec] = u.display_name.split(',').map(s => s.trim())
  // «Исследователь (обезличенные данные)»: скобки — пояснение, а не часть имени
  const [, name, note] = full.match(/^(.*?)\s*(?:\((.*)\))?$/) ?? [full, full]
  const w = name.split(/\s+/).filter(Boolean)
  const short = w.length === 3 ? `${w[0]} ${w[1][0]}. ${w[2][0]}.` : name
  const initials = (w.length > 1 ? w[0][0] + w[1][0] : name[0]).toUpperCase()
  return { short, sub: spec || note || ROLE_LABEL[u.role], initials }
}
