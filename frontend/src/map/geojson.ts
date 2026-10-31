/** Plan -> GeoJSON for the map sources. Built once per plan, never per frame. */
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'

import type { PlanResponse, RouteOption } from '../api/types'
import { formatDuration } from '../lib/format'

export const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] }

/** Stable numeric feature id so checkpoints can carry hover feature-state. */
export function checkpointFeatureId(routeIndex: number, checkpointIndex: number): number {
  return routeIndex * 100_000 + checkpointIndex
}

const collection = <G extends LineString | Point>(features: Feature<G>[]): FeatureCollection<G> => ({
  type: 'FeatureCollection',
  features,
})

export function routeLines(plan: PlanResponse): FeatureCollection<LineString> {
  return collection(
    plan.routes.map((route) => ({
      type: 'Feature',
      properties: { routeId: route.id },
      geometry: { type: 'LineString', coordinates: route.geometry },
    })),
  )
}

export function riskSegments(plan: PlanResponse): FeatureCollection<LineString> {
  return collection(
    plan.routes.flatMap((route) =>
      route.risk_segments.map((segment) => ({
        type: 'Feature' as const,
        properties: { routeId: route.id, level: segment.level },
        geometry: { type: 'LineString' as const, coordinates: segment.coordinates },
      })),
    ),
  )
}

export function checkpointPoints(plan: PlanResponse): FeatureCollection<Point> {
  return collection(
    plan.routes.flatMap((route, routeIndex) =>
      route.checkpoints.map((cp) => ({
        type: 'Feature' as const,
        id: checkpointFeatureId(routeIndex, cp.index),
        properties: { routeId: route.id, index: cp.index, level: cp.risk?.level ?? 'unknown' },
        geometry: { type: 'Point' as const, coordinates: [cp.lon, cp.lat] },
      })),
    ),
  )
}

export function stopPoints(plan: PlanResponse): FeatureCollection<Point> {
  return collection(
    plan.routes.flatMap((route) =>
      route.stops.map((stop) => ({
        type: 'Feature' as const,
        properties: {
          routeId: route.id,
          kind: stop.kind,
          label: stop.kind === 'break' ? '30m' : '10h',
        },
        geometry: { type: 'Point' as const, coordinates: [stop.lon, stop.lat] },
      })),
    ),
  )
}

export function endpoints(plan: PlanResponse): FeatureCollection<Point> {
  const short = (label: string) => label.split(',')[0]
  const { origin, destination } = plan.request
  return collection([
    {
      type: 'Feature',
      properties: { kind: 'origin', label: short(origin.label) },
      geometry: { type: 'Point', coordinates: [origin.lon, origin.lat] },
    },
    {
      type: 'Feature',
      properties: { kind: 'destination', label: short(destination.label) },
      geometry: { type: 'Point', coordinates: [destination.lon, destination.lat] },
    },
  ])
}

/** One label per route, staggered along each line so they don't stack on shared roads. */
export function routeLabels(plan: PlanResponse): FeatureCollection<Point> {
  return collection(
    plan.routes.map((route, i) => {
      const fraction = [0.42, 0.56, 0.7][i % 3]
      const coordinate = route.geometry[Math.floor((route.geometry.length - 1) * fraction)]
      return {
        type: 'Feature' as const,
        properties: { routeId: route.id, label: `${route.id} · ${formatDuration(route.trip_time_s)}` },
        geometry: { type: 'Point' as const, coordinates: coordinate },
      }
    }),
  )
}

export interface TruckPosition {
  routeId: string
  lon: number
  lat: number
  mile: number
  state: string
}

/** Truck position at a slider time, interpolated between the 15-minute track samples. */
export function truckAt(route: RouteOption, hours: number): TruckPosition {
  const { track } = route
  const last = track.coordinates.length - 1
  const position = Math.min(Math.max((hours * 3600) / track.step_s, 0), last)
  const i = Math.floor(position)
  const j = Math.min(i + 1, last)
  const t = position - i
  const [lon0, lat0] = track.coordinates[i]
  const [lon1, lat1] = track.coordinates[j]
  return {
    routeId: route.id,
    lon: lon0 + (lon1 - lon0) * t,
    lat: lat0 + (lat1 - lat0) * t,
    mile: track.miles[i] + (track.miles[j] - track.miles[i]) * t,
    state: track.states[Math.round(position)] ?? 'A',
  }
}

export function truckPoints(trucks: TruckPosition[]): FeatureCollection<Point> {
  return collection(
    trucks.map((truck) => ({
      type: 'Feature' as const,
      properties: { routeId: truck.routeId, state: truck.state },
      geometry: { type: 'Point' as const, coordinates: [truck.lon, truck.lat] },
    })),
  )
}

export function planBounds(plan: PlanResponse): [[number, number], [number, number]] {
  let west = Infinity
  let south = Infinity
  let east = -Infinity
  let north = -Infinity
  for (const route of plan.routes) {
    for (const [lon, lat] of route.geometry) {
      west = Math.min(west, lon)
      east = Math.max(east, lon)
      south = Math.min(south, lat)
      north = Math.max(north, lat)
    }
  }
  return [
    [west, south],
    [east, north],
  ]
}
