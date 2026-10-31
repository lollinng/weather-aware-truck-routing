import type { ExpressionSpecification, LayerSpecification, Map as MlMap } from 'maplibre-gl'

import { RISK_COLOR } from '../lib/risk'
import { EMPTY } from './geojson'

export const SOURCES = ['routes', 'segments', 'checkpoints', 'stops', 'endpoints', 'labels', 'trucks'] as const
export type SourceId = (typeof SOURCES)[number]

export const INK = '#0f1f2b'
const FONT = ['Noto Sans Bold']

const levelColor: ExpressionSpecification = [
  'match',
  ['get', 'level'],
  'low', RISK_COLOR.low,
  'moderate', RISK_COLOR.moderate,
  'high', RISK_COLOR.high,
  'severe', RISK_COLOR.severe,
  'no_travel', RISK_COLOR.no_travel,
  RISK_COLOR.unknown,
]

const hovered: ExpressionSpecification = ['boolean', ['feature-state', 'hover'], false]

/** Filters that split each route layer into "selected" and "other" copies. */
export const isSelected = (id: string): ExpressionSpecification => ['==', ['get', 'routeId'], id]
export const isOther = (id: string): ExpressionSpecification => ['!=', ['get', 'routeId'], id]

const zoomed = (z4: number, z10: number): ExpressionSpecification => [
  'interpolate', ['linear'], ['zoom'], 4, z4, 10, z10,
]

/** Layer stack, bottom to top. Layers ending in "-selected" are filtered to the selected route. */
const LAYERS: LayerSpecification[] = [
  // Unselected routes: thin, translucent, still risk-coloured so all options stay comparable.
  {
    id: 'routes-other-casing',
    type: 'line',
    source: 'routes',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#ffffff', 'line-width': zoomed(5, 9), 'line-opacity': 0.9 },
  },
  {
    id: 'segments-other',
    type: 'line',
    source: 'segments',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': levelColor, 'line-width': zoomed(2.5, 5), 'line-opacity': 0.55 },
  },
  {
    id: 'checkpoints-other',
    type: 'circle',
    source: 'checkpoints',
    minzoom: 5,
    paint: {
      'circle-color': levelColor,
      'circle-radius': zoomed(2, 4),
      'circle-opacity': 0.75,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 1,
    },
  },
  // Selected route on top.
  {
    id: 'routes-selected-casing',
    type: 'line',
    source: 'routes',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': INK, 'line-width': zoomed(9, 15), 'line-opacity': 0.85 },
  },
  {
    id: 'routes-selected-gap',
    type: 'line',
    source: 'routes',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': '#ffffff', 'line-width': zoomed(6.5, 11.5) },
  },
  {
    id: 'segments-selected',
    type: 'line',
    source: 'segments',
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': levelColor, 'line-width': zoomed(4.5, 8.5) },
  },
  {
    id: 'checkpoints-selected',
    type: 'circle',
    source: 'checkpoints',
    paint: {
      'circle-color': levelColor,
      // Zoom must be the outermost expression, so the hover case sits inside each stop.
      'circle-radius': [
        'interpolate', ['linear'], ['zoom'],
        3, ['case', hovered, 7, 3],
        6, ['case', hovered, 8.5, 4.5],
        10, ['case', hovered, 10, 6.5],
      ],
      'circle-stroke-color': ['case', hovered, INK, '#ffffff'],
      'circle-stroke-width': ['case', hovered, 2.5, 1.6],
    },
  },
  {
    id: 'stops-selected',
    type: 'circle',
    source: 'stops',
    paint: {
      'circle-color': '#ffffff',
      'circle-radius': zoomed(5, 8),
      'circle-stroke-color': INK,
      'circle-stroke-width': 2,
    },
  },
  {
    id: 'stops-selected-label',
    type: 'symbol',
    source: 'stops',
    layout: {
      'text-field': ['get', 'label'],
      'text-font': FONT,
      'text-size': 11,
      'text-offset': [0, 1.3],
      'text-anchor': 'top',
      'text-allow-overlap': false,
    },
    paint: { 'text-color': INK, 'text-halo-color': '#ffffff', 'text-halo-width': 1.6 },
  },
  {
    id: 'endpoints',
    type: 'circle',
    source: 'endpoints',
    paint: {
      'circle-color': ['match', ['get', 'kind'], 'origin', '#ffffff', INK],
      'circle-radius': 7,
      'circle-stroke-color': INK,
      'circle-stroke-width': 3,
    },
  },
  {
    id: 'endpoints-label',
    type: 'symbol',
    source: 'endpoints',
    layout: {
      'text-field': ['get', 'label'],
      'text-font': FONT,
      'text-size': 13,
      'text-offset': [0, 1.2],
      'text-anchor': 'top',
    },
    paint: { 'text-color': INK, 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
  },
  {
    id: 'trucks',
    type: 'circle',
    source: 'trucks',
    paint: {
      // Solid while driving, hollow while on a break/rest, faded once arrived.
      'circle-color': ['match', ['get', 'state'], 'D', INK, '#ffffff'],
      'circle-radius': 11,
      'circle-stroke-color': INK,
      'circle-stroke-width': 2.5,
      'circle-opacity': ['match', ['get', 'state'], 'A', 0.55, 1],
      'circle-stroke-opacity': ['match', ['get', 'state'], 'A', 0.55, 1],
    },
  },
  {
    id: 'trucks-label',
    type: 'symbol',
    source: 'trucks',
    layout: {
      'text-field': ['get', 'routeId'],
      'text-font': FONT,
      'text-size': 12,
      'text-allow-overlap': true,
      'text-ignore-placement': true,
    },
    paint: { 'text-color': ['match', ['get', 'state'], 'D', '#ffffff', INK] },
  },
  {
    id: 'labels',
    type: 'symbol',
    source: 'labels',
    layout: {
      'text-field': ['get', 'label'],
      'text-font': FONT,
      'text-size': 12,
      'icon-image': 'pill-light',
      'icon-text-fit': 'both',
      'icon-text-fit-padding': [3, 7, 3, 7],
      'text-allow-overlap': true,
      'icon-allow-overlap': true,
    },
    paint: { 'text-color': INK },
  },
]

/** Layers that only show the selected route vs. those that show the others. */
const SELECTED_ONLY = new Set([
  'routes-selected-casing',
  'routes-selected-gap',
  'segments-selected',
  'checkpoints-selected',
  'stops-selected',
  'stops-selected-label',
])
const OTHERS_ONLY = new Set(['routes-other-casing', 'segments-other', 'checkpoints-other'])

export const INTERACTIVE = {
  checkpoints: ['checkpoints-selected', 'checkpoints-other'],
  routes: ['segments-selected', 'segments-other', 'labels'],
  trucks: ['trucks'],
}

/** A rounded "pill" image that stretches around route labels. */
function addPillImage(map: MlMap, name: string, fill: string, stroke: string): void {
  const ratio = 2
  const size = 24 * ratio
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = fill
  ctx.strokeStyle = stroke
  ctx.lineWidth = 1.5 * ratio
  ctx.beginPath()
  ctx.roundRect(ctx.lineWidth, ctx.lineWidth, size - 2 * ctx.lineWidth, size - 2 * ctx.lineWidth, 9 * ratio)
  ctx.fill()
  ctx.stroke()
  const data = ctx.getImageData(0, 0, size, size)
  map.addImage(name, data, {
    pixelRatio: ratio,
    stretchX: [[10 * ratio, 14 * ratio]],
    stretchY: [[10 * ratio, 14 * ratio]],
    content: [6 * ratio, 6 * ratio, 18 * ratio, 18 * ratio],
  })
}

export function installLayers(map: MlMap): void {
  addPillImage(map, 'pill-light', '#ffffff', 'rgba(15,31,43,0.35)')
  addPillImage(map, 'pill-dark', INK, INK)
  for (const id of SOURCES) map.addSource(id, { type: 'geojson', data: EMPTY })
  for (const layer of LAYERS) map.addLayer(layer)
}

export function applySelection(map: MlMap, routeId: string): void {
  for (const id of SELECTED_ONLY) map.setFilter(id, isSelected(routeId))
  for (const id of OTHERS_ONLY) map.setFilter(id, isOther(routeId))
  map.setLayoutProperty('labels', 'icon-image', ['case', isSelected(routeId), 'pill-dark', 'pill-light'])
  map.setPaintProperty('labels', 'text-color', ['case', isSelected(routeId), '#ffffff', INK])
  map.setLayoutProperty('labels', 'symbol-sort-key', ['case', isSelected(routeId), 1, 0])
  map.setPaintProperty('trucks', 'circle-radius', ['case', isSelected(routeId), 12, 9])
}
