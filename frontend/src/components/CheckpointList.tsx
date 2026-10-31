import { memo, useMemo, useState } from 'react'

import type { Checkpoint, RouteOption, Stop } from '../api/types'
import { formatClock, formatHoursOffset, formatNumber } from '../lib/format'
import { FACTOR_LABEL, RISK_COLOR, RISK_LABEL, RISK_RANK } from '../lib/risk'
import type { CheckpointRef } from '../map/MapView'

interface CheckpointListProps {
  route: RouteOption
  intervalMiles: number
  hovered: CheckpointRef | null
  onHover: (ref: CheckpointRef | null) => void
  onPick: (ref: CheckpointRef) => void
}

type Row = { kind: 'checkpoint'; mile: number; cp: Checkpoint } | { kind: 'stop'; mile: number; stop: Stop }

function weatherSummary(cp: Checkpoint): string {
  const w = cp.weather
  if (!w) return 'No forecast'
  const parts = [`${formatNumber(w.wind_mph)} mph`]
  if (w.rain_in_hr >= 0.01) parts.push(`rain ${w.rain_in_hr.toFixed(2)}″/h`)
  if (w.snow_in_hr >= 0.01) parts.push(`snow ${w.snow_in_hr.toFixed(2)}″/h`)
  return parts.join(' · ')
}

export const CheckpointList = memo(function CheckpointList({
  route,
  intervalMiles,
  hovered,
  onHover,
  onPick,
}: CheckpointListProps) {
  const [elevatedOnly, setElevatedOnly] = useState(false)

  const rows = useMemo<Row[]>(() => {
    const checkpoints: Row[] = route.checkpoints
      .filter((cp) => !elevatedOnly || !cp.risk || RISK_RANK[cp.risk.level] > 0)
      .map((cp) => ({ kind: 'checkpoint', mile: cp.mile, cp }))
    const stops: Row[] = route.stops.map((stop) => ({ kind: 'stop', mile: stop.mile, stop }))
    return [...checkpoints, ...stops].sort((a, b) => a.mile - b.mile || (a.kind === 'stop' ? 1 : -1))
  }, [route, elevatedOnly])

  const elevatedCount = route.checkpoints.filter((cp) => cp.risk && RISK_RANK[cp.risk.level] > 0).length

  return (
    <section className="checkpoints" aria-label={`${route.name} checkpoints`}>
      <header className="section-head">
        <h2>
          {route.name} checkpoints{' '}
          <span className="muted">
            {route.checkpoints.length} · every {intervalMiles} mi
          </span>
        </h2>
        <label className="checkbox">
          <input type="checkbox" checked={elevatedOnly} onChange={(e) => setElevatedOnly(e.target.checked)} />
          Elevated only ({elevatedCount})
        </label>
      </header>
      {rows.length === 0 && <p className="checkpoints__empty">Every checkpoint on this route is Low risk.</p>}
      <ol className="checkpoints__list" onMouseLeave={() => onHover(null)}>
        {rows.map((row) => {
          if (row.kind === 'stop') {
            const { stop } = row
            return (
              <li key={`stop-${stop.mile}-${stop.kind}`} className="checkpoints__stop">
                <span className="checkpoints__stop-icon" aria-hidden="true">
                  {stop.kind === 'break' ? 'Ⅱ' : 'Z'}
                </span>
                <span>
                  {stop.kind === 'break' ? '30-min break' : '10-h rest'} at mile {formatNumber(stop.mile)}
                </span>
                <time>{formatClock(stop.start)}</time>
              </li>
            )
          }
          const { cp } = row
          const level = cp.risk?.level ?? 'unknown'
          const isHovered = hovered?.routeId === route.id && hovered.index === cp.index
          const ref = { routeId: route.id, index: cp.index }
          return (
            <li key={cp.index}>
              <button
                type="button"
                className={`checkpoint${isHovered ? ' is-hovered' : ''}`}
                onMouseEnter={() => onHover(ref)}
                onFocus={() => onHover(ref)}
                onClick={() => onPick(ref)}
              >
                <span className="checkpoint__dot" style={{ background: RISK_COLOR[level] }} aria-hidden="true" />
                <span className="checkpoint__mile">mi {formatNumber(cp.mile)}</span>
                <span className="checkpoint__time">
                  {formatClock(cp.eta)}
                  <small>{formatHoursOffset(cp.hours_from_departure)}</small>
                </span>
                <span className="checkpoint__wx">{weatherSummary(cp)}</span>
                <span className="checkpoint__level" style={{ color: level === 'low' ? undefined : RISK_COLOR[level] }}>
                  {RISK_LABEL[level]}
                  {cp.risk && cp.risk.drivers.length > 0 && (
                    <small>{cp.risk.drivers.map((d) => FACTOR_LABEL[d]).join(' + ')}{cp.risk.load_adjusted ? ' (load)' : ''}</small>
                  )}
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </section>
  )
})
