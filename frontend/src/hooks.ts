// Общие хуки интерфейса: ширина контейнера для графиков, плавный счёт чисел, учёт prefers-reduced-motion.
import { useEffect, useRef, useState } from 'react'
import { countUp } from './components/analytics/model'

export const reducedMotion = () =>
  typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/** Ширина элемента в CSS-пикселях: графики рисуются в реальную ширину, подписи не масштабируются. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    setW(el.clientWidth)
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

/** Число плавно доходит до значения (ease-out, ~0,7 с); при смене значения — от прежнего к новому.
 *  При prefers-reduced-motion сразу показывает итог. */
export function useCountUp(target: number, ms = 700): number {
  const [v, setV] = useState(() => (reducedMotion() ? target : 0))
  const from = useRef(v)
  useEffect(() => {
    if (reducedMotion()) { from.current = target; setV(target); return }
    const a = from.current, start = performance.now()
    let raf = 0
    const tick = (t: number) => {
      const k = (t - start) / ms
      const cur = countUp(a, target, t - start, ms)
      from.current = cur
      setV(cur)
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return v
}
