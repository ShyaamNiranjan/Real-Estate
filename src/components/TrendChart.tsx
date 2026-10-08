import { useState } from 'react'

type Point = { day: string; views: number; visitors: number }

const W = 1000
const H = 240

function path(points: Point[], key: 'views' | 'visitors', max: number) {
  if (!points.length) return ''
  const step = points.length > 1 ? W / (points.length - 1) : 0
  return points.map((p, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)},${(H - (p[key] / max) * (H - 12)).toFixed(1)}`).join(' ')
}

const shortDate = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

/** Views and unique visitors per day; hover (or tap) shows the exact numbers. */
export function TrendChart({ days, className = '' }: { days: Point[]; className?: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(4, ...days.map((d) => d.views))
  const views = path(days, 'views', max)
  const area = views ? `${views} L${W},${H} L0,${H} Z` : ''
  const ticks = days.length > 1 ? [0, Math.floor((days.length - 1) / 2), days.length - 1] : [0]
  const point = hover === null ? null : days[hover]

  const onMove = (clientX: number, el: HTMLElement) => {
    const r = el.getBoundingClientRect()
    const i = Math.round(((clientX - r.left) / r.width) * (days.length - 1))
    setHover(Math.min(days.length - 1, Math.max(0, i)))
  }

  return (
    <div className={`trend ${className}`}>
      <div
        className="trend__plot"
        onPointerMove={(e) => onMove(e.clientX, e.currentTarget)}
        onPointerDown={(e) => onMove(e.clientX, e.currentTarget)}
        onPointerLeave={() => setHover(null)}
      >
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
          {[0.25, 0.5, 0.75].map((f) => (
            <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} className="trend__grid" />
          ))}
          <path d={area} className="trend__area" />
          <path d={views} className="trend__line trend__line--views" vectorEffect="non-scaling-stroke" />
          <path d={path(days, 'visitors', max)} className="trend__line trend__line--visitors" vectorEffect="non-scaling-stroke" />
          {hover !== null && days.length > 1 && (
            <line x1={(hover / (days.length - 1)) * W} x2={(hover / (days.length - 1)) * W} y1="0" y2={H} className="trend__cursor" vectorEffect="non-scaling-stroke" />
          )}
        </svg>
        {point && (
          <div className="trend__tip" style={{ left: `${days.length > 1 ? (hover! / (days.length - 1)) * 100 : 50}%` }}>
            <strong>{shortDate(point.day)}</strong>
            <span>{point.views} views</span>
            <span>{point.visitors} visitors</span>
          </div>
        )}
      </div>
      <div className="trend__axis">
        {ticks.map((i) => (
          <span key={i}>{days[i] ? shortDate(days[i].day) : ''}</span>
        ))}
      </div>
      <div className="trend__legend">
        <span className="trend__key trend__key--views">Views</span>
        <span className="trend__key trend__key--visitors">Unique visitors</span>
      </div>
    </div>
  )
}
