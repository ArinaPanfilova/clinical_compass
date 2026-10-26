import { useTheme, type ThemePref } from '../theme'

const ICON = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const

const OPTIONS: [ThemePref, string, JSX.Element][] = [
  ['system', 'Тема как в системе', <svg key="s" {...ICON}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></svg>],
  ['light', 'Светлая тема', <svg key="l" {...ICON}><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4" /></svg>],
  ['dark', 'Тёмная тема', <svg key="d" {...ICON}><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" /></svg>],
]

/** Переключатель «системная / светлая / тёмная». */
export function ThemeToggle() {
  const [theme, setTheme] = useTheme()
  return (
    <div className="theme-toggle" role="group" aria-label="Тема оформления">
      {OPTIONS.map(([v, label, icon]) => (
        <button key={v} type="button" aria-pressed={theme === v} aria-label={label} title={label} onClick={() => setTheme(v)}>{icon}</button>
      ))}
    </div>
  )
}
