import type { RiskKey, SegmentLevel } from '../api/types'

export const RISK_LEVELS: RiskKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel']

export const RISK_LABEL: Record<SegmentLevel, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  severe: 'Severe',
  no_travel: 'No Travel',
  unknown: 'No data',
}

/** Shared by route lines, checkpoints, chips and the risk heatmap. */
export const RISK_COLOR: Record<SegmentLevel, string> = {
  low: '#2f9e44',
  moderate: '#e8a400',
  high: '#f76707',
  severe: '#e03131',
  no_travel: '#862e9c',
  unknown: '#868e96',
}

export const RISK_RANK: Record<RiskKey, number> = {
  low: 0,
  moderate: 1,
  high: 2,
  severe: 3,
  no_travel: 4,
}

export const FACTOR_LABEL = { wind: 'Wind', rain: 'Rain', snow: 'Snow' } as const
