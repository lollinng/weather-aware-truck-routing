import type { RiskSummary, RouteOption } from '../api/types'
import { formatClock, formatDuration, formatMiles } from '../lib/format'
import { RISK_COLOR, RISK_LABEL, RISK_LEVELS } from '../lib/risk'

export function RiskBar({ summary, total }: { summary: RiskSummary; total: number }) {
  const parts = [
    ...RISK_LEVELS.map((level) => ({ level, miles: summary.miles[level] })),
    { level: 'unknown' as const, miles: summary.unknown_miles },
  ].filter((part) => part.miles > 0)
  const label = parts.map((p) => `${RISK_LABEL[p.level]} ${formatMiles(p.miles)}`).join(', ')
  return (
    <div className="risk-bar" role="img" aria-label={`Miles by risk: ${label}`} title={label}>
      {parts.map((part) => (
        <span
          key={part.level}
          style={{ flexGrow: part.miles / total, background: RISK_COLOR[part.level] }}
        />
      ))}
    </div>
  )
}

interface RouteCardProps {
  route: RouteOption
  selected: boolean
  fastest: boolean
  hos: boolean
  onSelect: (id: string) => void
}

export function RouteCard({ route, selected, fastest, hos, onSelect }: RouteCardProps) {
  const { summary } = route
  const blocked = summary.miles.no_travel > 0
  return (
    <button
      type="button"
      className={`route-card${selected ? ' is-selected' : ''}${route.recommended ? ' is-recommended' : ''}`}
      onClick={() => onSelect(route.id)}
      aria-pressed={selected}
    >
      <div className="route-card__head">
        <span className="route-card__badge">{route.id}</span>
        <span className="route-card__via">{route.roads.length ? `via ${route.roads.slice(0, 2).join(' · ')}` : route.name}</span>
        <span className="route-card__tags">
          {route.recommended && <span className="tag tag--accent">Recommended</span>}
          {fastest && <span className="tag">Fastest</span>}
          {blocked && <span className="tag tag--danger">No-travel zone</span>}
        </span>
      </div>
      <div className="route-card__stats">
        <div>
          <strong>{formatDuration(route.trip_time_s)}</strong>
          <span>{hos && route.trip_time_s !== route.drive_time_s ? `${formatDuration(route.drive_time_s)} driving` : 'trip time'}</span>
        </div>
        <div>
          <strong>{formatMiles(route.distance_mi)}</strong>
          <span>distance</span>
        </div>
        <div>
          <strong>{formatClock(route.arrival)}</strong>
          <span>arrival</span>
        </div>
      </div>
      <RiskBar summary={summary} total={route.distance_mi} />
      <dl className="route-card__risk">
        {blocked && (
          <div>
            <dt>No travel</dt>
            <dd style={{ color: RISK_COLOR.no_travel }}>{formatMiles(summary.miles.no_travel)}</dd>
          </div>
        )}
        <div>
          <dt>Severe</dt>
          <dd>{formatMiles(summary.miles.severe)}</dd>
        </div>
        <div>
          <dt>High</dt>
          <dd>{formatMiles(summary.miles.high)}</dd>
        </div>
        <div>
          <dt>Avg risk</dt>
          <dd>{summary.average_risk.toFixed(2)}</dd>
        </div>
        <div>
          <dt>Worst</dt>
          <dd style={{ color: RISK_COLOR[summary.max_level] }}>{RISK_LABEL[summary.max_level]}</dd>
        </div>
      </dl>
    </button>
  )
}
