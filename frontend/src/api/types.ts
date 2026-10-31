/** Wire types for the Django API (see backend/planner/services/trip_planner.py). */

export type RiskKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel'
export type SegmentLevel = RiskKey | 'unknown'
export type HeatmapMetric = 'risk' | 'wind' | 'rain' | 'snow'
export type SamplingInterval = 10 | 25 | 50

export interface Place {
  label: string
  lat: number
  lon: number
}

export interface PlanRequest {
  origin: Place
  destination: Place
  departure: string // ISO 8601
  load_weight_lb: number
  interval_miles: SamplingInterval
  hos: boolean
}

export interface CheckpointWeather {
  wind_mph: number
  gust_mph: number | null
  rain_in_hr: number
  snow_in_hr: number
  temp_f: number | null
  weather_code: number | null
}

export interface CheckpointRisk {
  level: RiskKey
  wind: RiskKey
  rain: RiskKey
  snow: RiskKey
  load_adjusted: boolean
  drivers: Array<'wind' | 'rain' | 'snow'>
}

export interface Checkpoint {
  index: number
  mile: number
  lat: number
  lon: number
  eta: string
  hours_from_departure: number
  span_mi: number
  weather: CheckpointWeather | null
  risk: CheckpointRisk | null
}

export interface RiskSegment {
  level: SegmentLevel
  start_mi: number
  end_mi: number
  coordinates: [number, number][]
}

export interface Stop {
  kind: 'break' | 'rest'
  mile: number
  lat: number
  lon: number
  start: string
  duration_s: number
}

export interface Track {
  step_s: number
  coordinates: [number, number][]
  miles: number[]
  /** One char per sample: D driving, B break, R rest, A arrived. */
  states: string
}

export interface RiskSummary {
  miles: Record<RiskKey, number>
  unknown_miles: number
  average_risk: number
  max_level: RiskKey
}

export interface RouteOption {
  id: string
  name: string
  roads: string[]
  provider: string
  distance_mi: number
  drive_time_s: number
  trip_time_s: number
  arrival: string
  rank: number
  recommended: boolean
  summary: RiskSummary
  geometry: [number, number][]
  risk_segments: RiskSegment[]
  checkpoints: Checkpoint[]
  stops: Stop[]
  track: Track
}

export interface HeatmapData {
  lattice: { south: number; west: number; step: number; rows: number; cols: number }
  /** [row, col] of each corridor point; metric arrays are frame-major over these cells. */
  cells: [number, number][]
  frame0: string
  frame_count: number
  metrics: Record<HeatmapMetric, Array<number | null>>
}

export interface RoutingInfo {
  provider: string
  profile: 'truck' | 'car'
  /** Why the truck router wasn't used: trip too long, router down, or too few alternatives. */
  fallback_reason: 'distance' | 'unavailable' | 'alternatives' | null
}

export interface PlanResponse {
  request: PlanRequest
  routes: RouteOption[]
  recommendation: { route_id: string; reasons: string[]; warnings: string[] }
  routing: RoutingInfo
  /** Effective checkpoint spacing; coarser than requested if the forecast budget required it. */
  interval_miles: SamplingInterval
  notices: string[]
  heatmap: HeatmapData
}

export interface ApiErrorBody {
  detail?: string
  [field: string]: unknown
}
