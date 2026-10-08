import { useEffect, useRef, useState, type ReactNode } from 'react'

export const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)

/** Number that counts up to its value on first show, and tweens between values after that. */
export function CountUp({ value, format = (n) => Math.round(n).toLocaleString('en-US'), duration = 900 }: { value: number; format?: (n: number) => string; duration?: number }) {
  const [shown, setShown] = useState(() => (reducedMotion() ? value : 0))
  const from = useRef(shown)
  useEffect(() => {
    if (reducedMotion()) {
      setShown(value)
      return
    }
    const start = performance.now()
    const a = from.current
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const v = a + (value - a) * easeOut(t)
      from.current = v
      setShown(v)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  return <>{format(shown)}</>
}

/** True one frame after mount, so CSS transitions run from their starting state. */
export function useEntered() {
  const [on, setOn] = useState(false)
  useEffect(() => {
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => setOn(true)))
    return () => cancelAnimationFrame(raf)
  }, [])
  return on
}

export function Sparkline({ values, className = '' }: { values: number[]; className?: string }) {
  const W = 120
  const H = 36
  if (values.length < 2) return <svg className={`a-spark ${className}`} viewBox={`0 0 ${W} ${H}`} aria-hidden />
  const max = Math.max(1, ...values)
  const pts = values.map((v, i) => [(i / (values.length - 1)) * W, H - 3 - (v / max) * (H - 6)])
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  return (
    <svg className={`a-spark ${className}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
      <path d={`${line} L${W},${H} L0,${H} Z`} className="a-spark__area" />
      <path d={line} className="a-spark__line" pathLength={1} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/** Circular progress (0–1) that sweeps in from empty. */
export function Ring({ value, children }: { value: number; children?: ReactNode }) {
  const entered = useEntered()
  const r = 26
  const c = 2 * Math.PI * r
  return (
    <span className="a-ring">
      <svg viewBox="0 0 64 64" aria-hidden>
        <circle cx="32" cy="32" r={r} className="a-ring__track" />
        <circle cx="32" cy="32" r={r} className="a-ring__value" strokeDasharray={c} strokeDashoffset={entered ? c * (1 - Math.min(1, Math.max(0, value))) : c} />
      </svg>
      {children && <span className="a-ring__label">{children}</span>}
    </span>
  )
}

export function Skeleton({ w, h = 14, round = false, className = '' }: { w?: number | string; h?: number | string; round?: boolean; className?: string }) {
  return <span className={`a-skel ${round ? 'a-skel--round' : ''} ${className}`} style={{ width: w, height: h }} aria-hidden />
}

/** Placeholder shaped like a typical Studio page while its data loads. */
export function PageSkeleton({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="a-pageskel" role="status" aria-label={label}>
      <Skeleton w={110} h={10} />
      <Skeleton w="38%" h={34} />
      <div className="a-pageskel__row">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="a-pageskel__card">
            <Skeleton w="45%" h={10} />
            <Skeleton w="60%" h={28} />
            <Skeleton w="80%" h={10} />
          </div>
        ))}
      </div>
      <div className="a-pageskel__card a-pageskel__card--tall">
        <Skeleton w="30%" h={12} />
        <Skeleton w="100%" h={12} />
        <Skeleton w="92%" h={12} />
        <Skeleton w="96%" h={12} />
        <Skeleton w="70%" h={12} />
      </div>
    </div>
  )
}

const ICONS = {
  visitors: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 19c.6-3.3 3-5 6-5s5.4 1.7 6 5" />
      <path d="M16 5.2a3 3 0 0 1 0 5.6M18 14.3c1.7.6 2.8 2.1 3 4.7" />
    </>
  ),
  enquiries: (
    <>
      <path d="M4 5.5h16v10H9l-5 4v-14Z" />
      <path d="M8 9.5h8M8 12.5h5" />
    </>
  ),
  listings: (
    <>
      <path d="M3.5 11 12 4l8.5 7" />
      <path d="M5.5 9.5V20h13V9.5" />
      <path d="M10 20v-5.5h4V20" />
    </>
  ),
  walk: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m10 8.5 5.5 3.5-5.5 3.5v-7Z" />
    </>
  ),
  views: (
    <>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="2.8" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  rate: (
    <>
      <path d="M4 19 19 4" />
      <circle cx="6.5" cy="6.5" r="2.5" />
      <circle cx="17.5" cy="17.5" r="2.5" />
    </>
  ),
  arrow: <path d="M5 12h13M13 6.5 18.5 12 13 17.5" />,
}

export type IconName = keyof typeof ICONS

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {ICONS[name]}
    </svg>
  )
}

/** "▲ 12%" chip comparing with the previous period. */
export function Delta({ value, label = 'vs last period' }: { value: number | null; label?: string }) {
  if (value === null) return <span className="a-delta">New this period</span>
  const pct = Math.round(value * 100)
  const dir = pct > 0 ? 'is-up' : pct < 0 ? 'is-down' : ''
  return (
    <span className={`a-delta ${dir}`}>
      <b>
        {pct > 0 ? '▲' : pct < 0 ? '▼' : '•'} {Math.abs(pct)}%
      </b>{' '}
      {label}
    </span>
  )
}
