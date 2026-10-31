/**
 * Pure heatmap maths, independent of MapLibre so it can be unit tested.
 *
 * The backend samples forecasts on a regular lat/lon lattice around the routes. MapLibre maps
 * a canvas linearly in *Web Mercator*, so each canvas row is placed at its Mercator position
 * and the lattice is bilinearly sampled at that row's true latitude (lat/lon grids are not
 * linear in Mercator Y). Time is interpolated between hourly frames for smooth playback.
 */
import type { HeatmapData, HeatmapMetric } from '../api/types'
import { LUT_SIZE, type MetricScale } from './scales'

export const METRICS: HeatmapMetric[] = ['risk', 'wind', 'rain', 'snow']

export interface HeatmapGrid {
  rows: number
  cols: number
  frames: number
  /** frames × rows × cols, row 0 = southernmost; NaN outside the corridor or missing. */
  values: Record<HeatmapMetric, Float32Array>
}

export interface Sampler {
  width: number
  height: number
  /** Per pixel: lower-left lattice row/col and bilinear weights. */
  row: Int32Array
  col: Int32Array
  fx: Float32Array
  fy: Float32Array
  /** [top-left, top-right, bottom-right, bottom-left] as [lon, lat] for MapLibre. */
  corners: [[number, number], [number, number], [number, number], [number, number]]
}

export function buildGrid(data: HeatmapData): HeatmapGrid {
  const { rows, cols } = data.lattice
  const frames = data.frame_count
  const cellCount = data.cells.length
  const size = rows * cols
  const values = {} as Record<HeatmapMetric, Float32Array>
  for (const metric of METRICS) {
    const out = new Float32Array(frames * size).fill(Number.NaN)
    const source = data.metrics[metric]
    for (let f = 0; f < frames; f++) {
      for (let k = 0; k < cellCount; k++) {
        const v = source[f * cellCount + k]
        if (v !== null) {
          const [r, c] = data.cells[k]
          out[f * size + r * cols + c] = v
        }
      }
    }
    values[metric] = out
  }
  return { rows, cols, frames, values }
}

const mercatorY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))
const inverseMercatorY = (y: number) => (Math.atan(Math.exp(y)) * 360) / Math.PI - 90

export function buildSampler(lattice: HeatmapData['lattice'], upscale = 6): Sampler {
  const { south, west, step, rows, cols } = lattice
  const lonW = west - step / 2
  const lonE = west + (cols - 1) * step + step / 2
  const latS = south - step / 2
  const latN = south + (rows - 1) * step + step / 2
  const width = cols * upscale
  const height = rows * upscale
  const yN = mercatorY(latN)
  const yS = mercatorY(latS)
  const n = width * height
  const sampler: Sampler = {
    width,
    height,
    row: new Int32Array(n),
    col: new Int32Array(n),
    fx: new Float32Array(n),
    fy: new Float32Array(n),
    corners: [
      [lonW, latN],
      [lonE, latN],
      [lonE, latS],
      [lonW, latS],
    ],
  }
  for (let y = 0; y < height; y++) {
    const lat = inverseMercatorY(yN + ((y + 0.5) / height) * (yS - yN))
    const rf = (lat - south) / step
    const r0 = Math.floor(rf)
    for (let x = 0; x < width; x++) {
      const lon = lonW + ((x + 0.5) / width) * (lonE - lonW)
      const cf = (lon - west) / step
      const c0 = Math.floor(cf)
      const p = y * width + x
      sampler.row[p] = r0
      sampler.col[p] = c0
      sampler.fx[p] = cf - c0
      sampler.fy[p] = rf - r0
    }
  }
  return sampler
}

/** Cell values at a fractional frame index, interpolated linearly in time. */
export function blendFrame(
  grid: HeatmapGrid,
  metric: HeatmapMetric,
  frame: number,
  out: Float32Array = new Float32Array(grid.rows * grid.cols),
): Float32Array {
  const size = grid.rows * grid.cols
  const f = Math.min(Math.max(frame, 0), grid.frames - 1)
  const f0 = Math.floor(f)
  const f1 = Math.min(f0 + 1, grid.frames - 1)
  const t = f - f0
  const data = grid.values[metric]
  for (let i = 0; i < size; i++) {
    const a = data[f0 * size + i]
    const b = data[f1 * size + i]
    out[i] = Number.isNaN(a) ? b : Number.isNaN(b) ? a : a + (b - a) * t
  }
  return out
}

const smoothstep = (edge0: number, edge1: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}

/** Writes RGBA pixels for one frame; corridor edges fade out with lattice coverage. */
export function rasterize(
  sampler: Sampler,
  grid: Pick<HeatmapGrid, 'rows' | 'cols'>,
  cells: Float32Array,
  scale: MetricScale,
  lut: Uint8ClampedArray,
  out: Uint8ClampedArray,
): void {
  const { rows, cols } = grid
  const range = scale.max - scale.min
  const n = sampler.width * sampler.height
  for (let p = 0; p < n; p++) {
    const r0 = sampler.row[p]
    const c0 = sampler.col[p]
    const fx = sampler.fx[p]
    const fy = sampler.fy[p]
    let weight = 0
    let sum = 0
    for (let k = 0; k < 4; k++) {
      const r = r0 + (k >> 1)
      const c = c0 + (k & 1)
      if (r < 0 || r >= rows || c < 0 || c >= cols) continue
      const v = cells[r * cols + c]
      if (Number.isNaN(v)) continue
      const w = (k & 1 ? fx : 1 - fx) * (k >> 1 ? fy : 1 - fy)
      weight += w
      sum += w * v
    }
    const o = p * 4
    if (weight < 1e-4) {
      out[o + 3] = 0
      continue
    }
    const value = sum / weight
    const idx = Math.round(Math.min(1, Math.max(0, (value - scale.min) / range)) * (LUT_SIZE - 1)) * 4
    out[o] = lut[idx]
    out[o + 1] = lut[idx + 1]
    out[o + 2] = lut[idx + 2]
    out[o + 3] = lut[idx + 3] * smoothstep(0.15, 0.85, weight)
  }
}

/** Fractional heatmap frame for a slider position (hours after departure). */
export function frameIndex(frame0Iso: string, departureIso: string, hours: number): number {
  return (Date.parse(departureIso) - Date.parse(frame0Iso)) / 3_600_000 + hours
}
