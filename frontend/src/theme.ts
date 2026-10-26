// Тема интерфейса: системная / светлая / тёмная. Выбор хранится в localStorage,
// атрибут data-theme на <html> переключает токены в styles.css (до первой отрисовки его ставит index.html).
import { useEffect, useState } from 'react'
import { reducedMotion } from './hooks'

export type ThemePref = 'system' | 'light' | 'dark'

const KEY = 'kompas.theme'
const BAR = { light: '#ffffff', dark: '#1d1724' }      // строка состояния браузера = цвет верхней панели

export function readTheme(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch { return 'system' }
}

const systemDark = () => typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches

export function applyTheme(t: ThemePref) {
  const root = document.documentElement
  if (t === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', t)
  const dark = t === 'dark' || (t === 'system' && systemDark())
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? BAR.dark : BAR.light)
}

export function useTheme(): [ThemePref, (t: ThemePref) => void] {
  const [theme, setTheme] = useState<ThemePref>(readTheme)

  useEffect(() => {
    applyTheme(theme)
    if (theme !== 'system' || typeof matchMedia !== 'function') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const follow = () => applyTheme('system')
    mq.addEventListener('change', follow)
    return () => mq.removeEventListener('change', follow)
  }, [theme])

  const choose = (t: ThemePref) => {
    try { if (t === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, t) } catch { /* приватный режим */ }
    // Короткая смена цветов вместо резкого скачка; без анимации — если пользователь её отключил
    if (!reducedMotion()) {
      const root = document.documentElement
      root.classList.add('theme-switching')
      window.setTimeout(() => root.classList.remove('theme-switching'), 320)
    }
    setTheme(t)
  }
  return [theme, choose]
}
