import { memo } from 'react'

import type { PlanResponse, RoutingInfo } from '../api/types'
import type { CheckpointRef } from '../map/MapView'
import { CheckpointList } from './CheckpointList'
import { RouteCard } from './RouteCard'

interface ResultsProps {
  plan: PlanResponse
  selectedRouteId: string
  hovered: CheckpointRef | null
  onSelectRoute: (id: string) => void
  onHoverCheckpoint: (ref: CheckpointRef | null) => void
  onPickCheckpoint: (ref: CheckpointRef) => void
}

function routingNote(routing: RoutingInfo): string {
  if (routing.profile === 'truck') return 'Truck routing (Valhalla) using your gross weight.'
  const why = {
    distance: 'the trip is longer than the public truck router allows (1,500 km straight-line)',
    unavailable: 'the truck router is unavailable right now',
    alternatives: 'the truck router could not find three distinct routes',
  }[routing.fallback_reason ?? 'unavailable']
  return `Car-profile routing (OSRM) because ${why}; truck restrictions are not applied.`
}

/** Sidebar results. Memoised: it doesn't depend on the slider, so playback never re-renders it. */
export const Results = memo(function Results({
  plan,
  selectedRouteId,
  hovered,
  onSelectRoute,
  onHoverCheckpoint,
  onPickCheckpoint,
}: ResultsProps) {
  const { recommendation, routes } = plan
  const recommended = routes.find((r) => r.id === recommendation.route_id)!
  const fastestId = routes.reduce((a, b) => (b.trip_time_s < a.trip_time_s ? b : a)).id
  const selected = routes.find((r) => r.id === selectedRouteId) ?? recommended

  return (
    <div className="results">
      <section className="recommendation" aria-live="polite">
        <p className="recommendation__eyebrow">Recommended</p>
        <h2 className="recommendation__title">
          <span className="route-card__badge">{recommended.id}</span>
          {recommended.roads.length ? `via ${recommended.roads.slice(0, 2).join(' · ')}` : recommended.name}
        </h2>
        <ul className="recommendation__reasons">
          {recommendation.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        {[...plan.notices, ...recommendation.warnings].map((warning) => (
          <p key={warning} className="callout callout--warning">
            {warning}
          </p>
        ))}
      </section>

      <section aria-label="Route options">
        <header className="section-head">
          <h2>
            Route options <span className="muted">{routes.length}</span>
          </h2>
          <span className="muted small">Ranked by severe → high miles → avg risk → time</span>
        </header>
        <p className="routing-note">{routingNote(plan.routing)}</p>
        {routes.length < 3 && (
          <p className="callout">Only {routes.length} distinct route{routes.length === 1 ? '' : 's'} found for this trip.</p>
        )}
        <div className="route-list">
          {[...routes]
            .sort((a, b) => a.rank - b.rank)
            .map((route) => (
              <RouteCard
                key={route.id}
                route={route}
                selected={route.id === selected.id}
                fastest={route.id === fastestId}
                hos={plan.request.hos}
                onSelect={onSelectRoute}
              />
            ))}
        </div>
      </section>

      <CheckpointList
        route={selected}
        intervalMiles={plan.interval_miles}
        hovered={hovered}
        onHover={onHoverCheckpoint}
        onPick={onPickCheckpoint}
      />
    </div>
  )
})
