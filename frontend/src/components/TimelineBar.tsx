import { memo } from 'react'

import type { HeatmapMetric, PlanResponse } from '../api/types'
import { METRICS } from '../heatmap/raster'
import { cssGradient, SCALES } from '../heatmap/scales'
import { addHours, formatClock, formatHoursOffset } from '../lib/format'

export const MAX_HOURS = 48
const TICKS = [0, 12, 24, 36, 48]

interface TimelineBarProps {
  plan: PlanResponse
  selectedRouteId: string
  hours: number
  playing: boolean
  metric: HeatmapMetric
  heatmapVisible: boolean
  onHoursChange: (hours: number) => void
  onTogglePlay: () => void
  onMetricChange: (metric: HeatmapMetric) => void
  onToggleHeatmap: () => void
}

function Legend({ metric }: { metric: HeatmapMetric }) {
  const scale = SCALES[metric]
  const span = scale.max - scale.min
  return (
    <div className="legend" aria-label={`${scale.label} colour scale`}>
      <div className="legend__bar" style={{ background: cssGradient(scale) }} />
      <div className="legend__ticks">
        {scale.ticks.map((tick) => (
          <span key={tick.value} style={{ left: `${((tick.value - scale.min) / span) * 100}%` }}>
            {tick.label}
          </span>
        ))}
      </div>
      {scale.unit && <span className="legend__unit">{scale.unit}</span>}
    </div>
  )
}

/** Floating 0–48 h forecast scrubber with playback, heatmap metric picker and legend. */
export const TimelineBar = memo(function TimelineBar(props: TimelineBarProps) {
  const { plan, selectedRouteId, hours, playing, metric, heatmapVisible } = props
  const departure = plan.request.departure
  const selected = plan.routes.find((r) => r.id === selectedRouteId)
  const arrivalHours = selected ? selected.trip_time_s / 3600 : null
  const at = addHours(departure, hours)

  return (
    <div className="timeline" role="group" aria-label="Forecast time">
      <div className="timeline__top">
        <button
          type="button"
          className="timeline__play"
          onClick={props.onTogglePlay}
          aria-label={playing ? 'Pause' : 'Play forecast'}
        >
          {playing ? (
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M7 5h3v14H7zM14 5h3v14h-3z" fill="currentColor" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M8 5.5v13l11-6.5z" fill="currentColor" />
            </svg>
          )}
        </button>
        <div className="timeline__clock">
          <strong>{formatClock(at)}</strong>
          <span>{hours < 0.01 ? 'departure' : `${formatHoursOffset(hours)} after departure`}</span>
        </div>
        <div className="timeline__controls">
          <div className="segmented segmented--small" role="radiogroup" aria-label="Heatmap layer">
            {METRICS.map((m) => (
              <label key={m} className={metric === m ? 'is-selected' : undefined}>
                <input type="radio" name="metric" checked={metric === m} onChange={() => props.onMetricChange(m)} />
                {SCALES[m].label}
              </label>
            ))}
          </div>
          <label className="toggle toggle--small">
            <input type="checkbox" checked={heatmapVisible} onChange={props.onToggleHeatmap} />
            <span className="toggle__track" aria-hidden="true" />
            <span className="toggle__text">Heatmap</span>
          </label>
        </div>
      </div>

      <div className="timeline__track">
        <input
          type="range"
          min={0}
          max={MAX_HOURS}
          step={0.25}
          value={hours}
          onChange={(e) => props.onHoursChange(Number(e.target.value))}
          aria-label="Hours after departure"
          aria-valuetext={`${formatClock(at)}, ${formatHoursOffset(hours)} after departure`}
          style={{ '--progress': `${(hours / MAX_HOURS) * 100}%` } as React.CSSProperties}
        />
        {arrivalHours !== null && arrivalHours <= MAX_HOURS && (
          <span
            className="timeline__arrival"
            style={{ left: `${(arrivalHours / MAX_HOURS) * 100}%` }}
            title={`Route ${selectedRouteId} arrives ${formatClock(addHours(departure, arrivalHours))}`}
          />
        )}
        <div className="timeline__ticks" aria-hidden="true">
          {TICKS.map((tick) => (
            <span key={tick} style={{ left: `${(tick / MAX_HOURS) * 100}%` }}>
              {tick === 0 ? 'Depart' : formatClock(addHours(departure, tick))}
            </span>
          ))}
        </div>
      </div>

      {heatmapVisible && <Legend metric={metric} />}
    </div>
  )
})
