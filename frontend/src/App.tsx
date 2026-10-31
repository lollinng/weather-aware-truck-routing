import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, planTrip, warmUp } from './api/client'
import type { HeatmapMetric, PlanRequest, PlanResponse } from './api/types'
import { Results } from './components/Results'
import { MAX_HOURS, TimelineBar } from './components/TimelineBar'
import { TripForm } from './components/TripForm'
import { usePlayback } from './hooks/usePlayback'
import { MapView, type CheckpointRef, type MapFocus } from './map/MapView'

const PLAYBACK_HOURS_PER_SECOND = 3.5
const SLOW_REQUEST_MS = 12_000
const MAP_PADDING = { top: 70, right: 70, bottom: 200, left: 70 }

export default function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [hovered, setHovered] = useState<CheckpointRef | null>(null)
  const [hours, setHours] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [metric, setMetric] = useState<HeatmapMetric>('risk')
  const [heatmapVisible, setHeatmapVisible] = useState(true)
  const [focus, setFocus] = useState<MapFocus | null>(null)
  const [slow, setSlow] = useState(false)
  const inflight = useRef<AbortController | null>(null)

  useEffect(warmUp, [])

  usePlayback(playing, hours, setHours, {
    hoursPerSecond: PLAYBACK_HOURS_PER_SECOND,
    maxHours: MAX_HOURS,
    onEnd: () => setPlaying(false),
  })

  const handlePlan = useCallback(async (request: PlanRequest) => {
    inflight.current?.abort()
    const controller = new AbortController()
    inflight.current = controller
    setLoading(true)
    setSlow(false)
    setError(null)
    setPlaying(false)
    const slowTimer = window.setTimeout(() => setSlow(true), SLOW_REQUEST_MS)
    try {
      const result = await planTrip(request, controller.signal)
      setPlan(result)
      setSelectedRouteId(result.recommendation.route_id)
      setHovered(null)
      setHours(0)
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      setError(err instanceof ApiError ? err : new ApiError(0, 'Something went wrong while planning.'))
    } finally {
      window.clearTimeout(slowTimer)
      if (inflight.current === controller) setLoading(false)
    }
  }, [])

  const handlePickCheckpoint = useCallback(
    (ref: CheckpointRef) => {
      const cp = plan?.routes.find((r) => r.id === ref.routeId)?.checkpoints[ref.index]
      if (!cp) return
      setSelectedRouteId(ref.routeId)
      setPlaying(false)
      setHours(Math.min(MAX_HOURS, cp.hours_from_departure))
      setFocus({ lon: cp.lon, lat: cp.lat, key: Date.now() })
    },
    [plan],
  )

  const togglePlay = useCallback(() => {
    if (!playing && hours >= MAX_HOURS) setHours(0) // replay from departure
    setPlaying(!playing)
  }, [playing, hours])

  const handleHoursChange = useCallback((value: number) => {
    setPlaying(false)
    setHours(value)
  }, [])

  const toggleHeatmap = useCallback(() => setHeatmapVisible((v) => !v), [])

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="brand">
          <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width="32" height="32" />
          <div>
            <h1>Weather-Aware Truck Routing</h1>
            <p>Three truck routes, forecasts at each checkpoint's ETA, load-aware risk.</p>
          </div>
        </header>

        <TripForm loading={loading} fieldErrors={error?.fields ?? {}} onSubmit={handlePlan} />

        {error && (
          <p className="callout callout--error" role="alert">
            {error.message}
          </p>
        )}

        {plan && selectedRouteId && (
          <Results
            plan={plan}
            selectedRouteId={selectedRouteId}
            hovered={hovered}
            onSelectRoute={setSelectedRouteId}
            onHoverCheckpoint={setHovered}
            onPickCheckpoint={handlePickCheckpoint}
          />
        )}

        <footer className="sidebar__footer">
          Routing: Valhalla (truck profile) · Weather: Open-Meteo · Map: OpenFreeMap / OpenStreetMap
        </footer>
      </aside>

      <main className="stage">
        <MapView
          plan={plan}
          selectedRouteId={selectedRouteId}
          hovered={hovered}
          timeHours={hours}
          metric={metric}
          heatmapVisible={heatmapVisible}
          focus={focus}
          padding={MAP_PADDING}
          onSelectRoute={setSelectedRouteId}
          onHoverCheckpoint={setHovered}
          onPickCheckpoint={handlePickCheckpoint}
        />

        {loading && (
          <div className="stage__overlay" role="status">
            <div className="loading-card">
              <span className="spinner spinner--large" aria-hidden="true" />
              <div>
                <strong>Planning your trip…</strong>
                <span>
                  {slow
                    ? 'Still working – the free-tier server may be waking up (up to a minute).'
                    : 'Finding truck routes, timing each checkpoint and pulling forecasts.'}
                </span>
              </div>
            </div>
          </div>
        )}

        {!plan && !loading && (
          <div className="stage__empty">
            <strong>Plan a trip to compare routes</strong>
            <span>Routes are coloured by weather risk at the time the truck reaches each stretch.</span>
          </div>
        )}

        {plan && selectedRouteId && (
          <TimelineBar
            plan={plan}
            selectedRouteId={selectedRouteId}
            hours={hours}
            playing={playing}
            metric={metric}
            heatmapVisible={heatmapVisible}
            onHoursChange={handleHoursChange}
            onTogglePlay={togglePlay}
            onMetricChange={setMetric}
            onToggleHeatmap={toggleHeatmap}
          />
        )}
      </main>
    </div>
  )
}
