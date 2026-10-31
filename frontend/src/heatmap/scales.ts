import type { HeatmapMetric } from '../api/types'

export type RGBA = readonly [number, number, number, number] // alpha in 0..1

export interface ColorStop {
  value: number
  color: RGBA
}

export interface MetricScale {
  label: string
  unit: string
  min: number
  max: number
  stops: ColorStop[]
  /** Legend ticks; for weather metrics these are the risk-table thresholds. */
  ticks: { value: number; label: string }[]
}

const TRANSPARENT: RGBA = [255, 255, 255, 0]
const LOW_RISK: RGBA = [47, 158, 68, 0.14]
const MODERATE: RGBA = [232, 164, 0, 0.5]
const HIGH: RGBA = [247, 103, 7, 0.6]
const SEVERE: RGBA = [224, 49, 49, 0.68]
const NO_TRAVEL: RGBA = [134, 46, 156, 0.78]

/**
 * Colour ramps. Weather metrics change colour exactly at the risk-table thresholds, so the
 * heatmap reads the same way as the checkpoint risk chips: yellow = Moderate, orange = High…
 */
export const SCALES: Record<HeatmapMetric, MetricScale> = {
  risk: {
    label: 'Risk',
    unit: '',
    min: 0,
    max: 4,
    stops: [
      { value: 0, color: LOW_RISK },
      { value: 1, color: MODERATE },
      { value: 2, color: HIGH },
      { value: 3, color: SEVERE },
      { value: 4, color: NO_TRAVEL },
    ],
    ticks: [
      { value: 0, label: 'Low' },
      { value: 1, label: 'Mod' },
      { value: 2, label: 'High' },
      { value: 3, label: 'Severe' },
      { value: 4, label: 'No travel' },
    ],
  },
  wind: {
    label: 'Wind',
    unit: 'mph',
    min: 0,
    max: 60,
    stops: [
      { value: 0, color: [76, 141, 214, 0] },
      { value: 12, color: [76, 141, 214, 0.16] },
      { value: 25, color: MODERATE },
      { value: 35, color: HIGH },
      { value: 45, color: SEVERE },
      { value: 55, color: NO_TRAVEL },
    ],
    ticks: [25, 35, 45, 55].map((v) => ({ value: v, label: String(v) })),
  },
  rain: {
    label: 'Rain',
    unit: 'in/hr',
    min: 0,
    max: 1.2,
    stops: [
      { value: 0, color: TRANSPARENT },
      { value: 0.005, color: [34, 139, 230, 0.12] },
      { value: 0.05, color: [34, 139, 230, 0.38] },
      { value: 0.1, color: MODERATE },
      { value: 0.25, color: HIGH },
      { value: 0.5, color: SEVERE },
      { value: 1.0, color: NO_TRAVEL },
    ],
    ticks: [0.1, 0.25, 0.5, 1.0].map((v) => ({ value: v, label: String(v) })),
  },
  snow: {
    label: 'Snow',
    unit: 'in/hr',
    min: 0,
    max: 3.5,
    stops: [
      { value: 0, color: TRANSPARENT },
      { value: 0.02, color: [116, 192, 252, 0.2] },
      { value: 0.25, color: [116, 192, 252, 0.45] },
      { value: 0.5, color: MODERATE },
      { value: 1.0, color: HIGH },
      { value: 2.0, color: SEVERE },
      { value: 3.0, color: NO_TRAVEL },
    ],
    ticks: [0.5, 1, 2, 3].map((v) => ({ value: v, label: String(v) })),
  },
}

export const LUT_SIZE = 512

function colorAt(stops: ColorStop[], value: number): RGBA {
  if (value <= stops[0].value) return stops[0].color
  for (let i = 1; i < stops.length; i++) {
    const hi = stops[i]
    if (value <= hi.value) {
      const lo = stops[i - 1]
      const t = (value - lo.value) / (hi.value - lo.value)
      return [0, 1, 2, 3].map((k) => lo.color[k] + (hi.color[k] - lo.color[k]) * t) as unknown as RGBA
    }
  }
  return stops[stops.length - 1].color
}

/** RGBA (alpha 0..255) lookup table spanning [scale.min, scale.max]. */
export function buildLut(scale: MetricScale, size = LUT_SIZE): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(size * 4)
  for (let i = 0; i < size; i++) {
    const value = scale.min + ((scale.max - scale.min) * i) / (size - 1)
    const [r, g, b, a] = colorAt(scale.stops, value)
    lut.set([r, g, b, a * 255], i * 4)
  }
  return lut
}

/** CSS gradient for the legend, sampled from the same ramp the map uses. */
export function cssGradient(scale: MetricScale, samples = 24): string {
  const parts: string[] = []
  for (let i = 0; i < samples; i++) {
    const t = i / (samples - 1)
    const [r, g, b, a] = colorAt(scale.stops, scale.min + (scale.max - scale.min) * t)
    // Legends sit on white; lift alpha so faint low values are still visible.
    parts.push(`rgba(${r},${g},${b},${Math.min(1, a * 1.35 + 0.08).toFixed(3)}) ${(t * 100).toFixed(1)}%`)
  }
  return `linear-gradient(90deg, ${parts.join(', ')})`
}
