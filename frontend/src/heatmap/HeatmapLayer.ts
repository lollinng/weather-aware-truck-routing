import type { CanvasSource, Map as MlMap } from 'maplibre-gl'

import type { HeatmapData, HeatmapMetric } from '../api/types'
import { blendFrame, buildGrid, buildSampler, rasterize, type HeatmapGrid, type Sampler } from './raster'
import { buildLut, SCALES } from './scales'

const SOURCE_ID = 'weather-heatmap'
const LAYER_ID = 'weather-heatmap'

/**
 * Weather heatmap drawn into a small offscreen canvas and shown as a MapLibre canvas source.
 *
 * Each slider change re-rasterises a few thousand pixels on the CPU (well under a millisecond)
 * and uploads them as one texture; the GPU's linear filtering smooths the result further. The
 * source is never animated, so the map only repaints when the frame actually changes.
 */
export class HeatmapLayer {
  private readonly map: MlMap
  private readonly canvas = document.createElement('canvas')
  private readonly ctx = this.canvas.getContext('2d')!
  private readonly luts = Object.fromEntries(
    Object.entries(SCALES).map(([metric, scale]) => [metric, buildLut(scale)]),
  ) as Record<HeatmapMetric, Uint8ClampedArray>
  private grid: HeatmapGrid | null = null
  private sampler: Sampler | null = null
  private image: ImageData | null = null
  private cells: Float32Array | null = null
  private lastKey = ''

  constructor(map: MlMap, beforeId?: string) {
    this.map = map
    this.canvas.width = this.canvas.height = 1
    map.addSource(SOURCE_ID, {
      type: 'canvas',
      canvas: this.canvas,
      animate: false,
      coordinates: [
        [0, 0.001],
        [0.001, 0.001],
        [0.001, 0],
        [0, 0],
      ],
    })
    map.addLayer(
      {
        id: LAYER_ID,
        type: 'raster',
        source: SOURCE_ID,
        paint: { 'raster-opacity': 0.92, 'raster-fade-duration': 0, 'raster-resampling': 'linear' },
      },
      beforeId,
    )
  }

  setData(data: HeatmapData | null): void {
    this.lastKey = ''
    if (!data || data.cells.length === 0) {
      this.grid = this.sampler = this.image = this.cells = null
      this.setVisible(false)
      return
    }
    this.grid = buildGrid(data)
    this.sampler = buildSampler(data.lattice)
    this.canvas.width = this.sampler.width
    this.canvas.height = this.sampler.height
    this.image = this.ctx.createImageData(this.sampler.width, this.sampler.height)
    this.cells = new Float32Array(this.grid.rows * this.grid.cols)
    this.source().setCoordinates(this.sampler.corners)
  }

  /** Draws the heatmap at a fractional frame index (0 = first forecast hour). */
  render(frame: number, metric: HeatmapMetric): void {
    const { grid, sampler, image, cells } = this
    if (!grid || !sampler || !image || !cells) return
    const key = `${metric}:${frame.toFixed(3)}`
    if (key === this.lastKey) return
    this.lastKey = key
    blendFrame(grid, metric, frame, cells)
    rasterize(sampler, grid, cells, SCALES[metric], this.luts[metric], image.data)
    this.ctx.putImageData(image, 0, 0)
    // play() + pause() uploads the canvas once (pause snapshots it) and schedules a repaint.
    const source = this.source()
    source.play()
    source.pause()
  }

  setVisible(visible: boolean): void {
    if (this.map.getLayer(LAYER_ID)) {
      this.map.setLayoutProperty(LAYER_ID, 'visibility', visible && this.grid ? 'visible' : 'none')
    }
  }

  private source(): CanvasSource {
    return this.map.getSource(SOURCE_ID) as CanvasSource
  }
}
