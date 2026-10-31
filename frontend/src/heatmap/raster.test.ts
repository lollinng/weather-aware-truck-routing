import { describe, expect, it } from 'vitest'

import type { HeatmapData } from '../api/types'
import { blendFrame, buildGrid, buildSampler, frameIndex, rasterize } from './raster'
import { buildLut, SCALES } from './scales'

const data: HeatmapData = {
  lattice: { south: 40, west: -100, step: 0.5, rows: 2, cols: 3 },
  cells: [
    [0, 0],
    [0, 1],
    [1, 1],
  ],
  frame0: '2026-11-02T12:00:00Z',
  frame_count: 2,
  metrics: {
    wind: [10, 20, 30, 20, 40, null],
    risk: [0, 0, 0, 1, 2, 3],
    rain: [0, 0, 0, 0, 0, 0],
    snow: [0, 0, 0, 0, 0, 0],
  },
}

describe('buildGrid', () => {
  it('places cell values on the lattice and leaves the rest NaN', () => {
    const grid = buildGrid(data)
    const frame0 = Array.from(grid.values.wind.slice(0, 6))
    expect(frame0.slice(0, 2)).toEqual([10, 20])
    expect(frame0[4]).toBe(30) // row 1, col 1
    expect(frame0.filter(Number.isNaN)).toHaveLength(3)
  })
})

describe('blendFrame', () => {
  it('interpolates in time and falls back to the available frame', () => {
    const grid = buildGrid(data)
    const cells = blendFrame(grid, 'wind', 0.5)
    expect(cells[0]).toBeCloseTo(15)
    expect(cells[1]).toBeCloseTo(30)
    expect(cells[4]).toBeCloseTo(30) // frame 1 missing -> keep frame 0
  })

  it('clamps out-of-range frames', () => {
    const grid = buildGrid(data)
    expect(blendFrame(grid, 'wind', 7)[0]).toBe(20)
    expect(blendFrame(grid, 'wind', -3)[0]).toBe(10)
  })
})

describe('buildSampler', () => {
  it('covers the lattice extent with Mercator-placed rows', () => {
    const sampler = buildSampler(data.lattice, 4)
    expect(sampler.width).toBe(12)
    expect(sampler.height).toBe(8)
    expect(sampler.corners[0]).toEqual([-100.25, 40.75])
    expect(sampler.corners[2]).toEqual([-98.75, 39.75])
    // Top rows sample the northern lattice row, bottom rows the southern one.
    expect(sampler.row[0]).toBe(1)
    expect(sampler.row[sampler.width * (sampler.height - 1)]).toBe(-1)
  })
})

describe('rasterize', () => {
  it('colours corridor pixels and leaves pixels far from data transparent', () => {
    const grid = buildGrid(data)
    const sampler = buildSampler(data.lattice, 4)
    const out = new Uint8ClampedArray(sampler.width * sampler.height * 4)
    const cells = blendFrame(grid, 'risk', 1)
    rasterize(sampler, grid, cells, SCALES.risk, buildLut(SCALES.risk), out)
    const alphaAt = (x: number, y: number) => out[(y * sampler.width + x) * 4 + 3]
    expect(alphaAt(6, 1)).toBeGreaterThan(100) // near the High/Severe cells in the north
    expect(alphaAt(11, 7)).toBe(0) // south-east corner has no data nearby
  })
})

describe('frameIndex', () => {
  it('offsets the slider by the departure minutes past the first frame', () => {
    expect(frameIndex('2026-11-02T12:00:00Z', '2026-11-02T12:30:00Z', 2)).toBeCloseTo(2.5)
  })
})
