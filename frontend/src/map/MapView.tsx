import {
  AttributionControl,
  Map as MlMap,
  NavigationControl,
  Popup,
  type GeoJSONSource,
  type MapMouseEvent,
  type PointLike,
  setWorkerUrl,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { HeatmapMetric, PlanResponse } from '../api/types'
import { HeatmapLayer } from '../heatmap/HeatmapLayer'
import { frameIndex } from '../heatmap/raster'
import { addHours } from '../lib/format'
import {
  checkpointFeatureId,
  checkpointPoints,
  EMPTY,
  endpoints,
  planBounds,
  riskSegments,
  routeLabels,
  routeLines,
  stopPoints,
  truckAt,
  truckPoints,
} from './geojson'
import { applySelection, installLayers, INTERACTIVE, SOURCES, type SourceId } from './layers'
import { checkpointPopup, truckPopup } from './popups'

// MapLibre 6 runs its tile worker from a separate module; let Vite emit it and point at it.
setWorkerUrl(workerUrl)

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const ATTRIBUTION = [
  '<a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Weather: Open-Meteo</a>',
  '<a href="https://valhalla.github.io/valhalla/" target="_blank" rel="noreferrer">Routing: Valhalla</a>',
]

export interface CheckpointRef {
  routeId: string
  index: number
}

export interface MapFocus {
  lon: number
  lat: number
  key: number
}

interface MapViewProps {
  plan: PlanResponse | null
  selectedRouteId: string | null
  hovered: CheckpointRef | null
  timeHours: number
  metric: HeatmapMetric
  heatmapVisible: boolean
  focus: MapFocus | null
  /** Space covered by floating UI, so fitBounds keeps the routes visible. */
  padding: { top: number; right: number; bottom: number; left: number }
  onSelectRoute: (routeId: string) => void
  onHoverCheckpoint: (ref: CheckpointRef | null) => void
  onPickCheckpoint: (ref: CheckpointRef) => void
}

/**
 * Imperative MapLibre wrapper. The map is created once; each effect below syncs one slice of
 * props to the map with the cheapest call available (setData / setFilter / feature-state), so
 * scrubbing the time slider only touches the truck source and the heatmap texture.
 */
export function MapView(props: MapViewProps) {
  const { plan, selectedRouteId, hovered, timeHours, metric, heatmapVisible, focus } = props
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MlMap | null>(null)
  const heatmapRef = useRef<HeatmapLayer | null>(null)
  const hoverPopup = useRef(new Popup({ closeButton: false, offset: 12, maxWidth: '280px' }))
  const truckPopupRef = useRef(new Popup({ closeButton: false, offset: 16, maxWidth: '240px' }))
  const hoveredTruck = useRef<string | null>(null)
  // Latest props for map event handlers, which are bound once.
  const latest = useRef(props)
  useLayoutEffect(() => {
    latest.current = props
  })
  const [ready, setReady] = useState(false)

  // Create the map once.
  useEffect(() => {
    const container = containerRef.current!
    const map = new MlMap({
      container,
      style: STYLE_URL,
      center: [-97.5, 39],
      zoom: 3.6,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      maxPitch: 0,
    })
    map.touchZoomRotate.disableRotation()
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(
      new AttributionControl({ compact: true, customAttribution: ATTRIBUTION }),
      'bottom-right',
    )
    map.on('load', () => {
      const firstLabel = map.getStyle().layers.find((layer) => layer.type === 'symbol')?.id
      heatmapRef.current = new HeatmapLayer(map, firstLabel) // under basemap labels
      installLayers(map)
      bindInteractions(map)
      setReady(true)
    })
    mapRef.current = map
    const resize = new ResizeObserver(() => map.resize())
    resize.observe(container)
    return () => {
      resize.disconnect()
      map.remove()
      mapRef.current = null
      heatmapRef.current = null
    }
  }, [])

  function bindInteractions(map: MlMap) {
    let hoverKey = ''
    const pickCheckpoint = (e: MapMouseEvent) =>
      map.queryRenderedFeatures(e.point, { layers: INTERACTIVE.checkpoints })[0]

    map.on('mousemove', (e) => {
      const feature = pickCheckpoint(e)
      const truck = map.queryRenderedFeatures(e.point, { layers: INTERACTIVE.trucks })[0]
      const route = feature || truck ? undefined : nearestRoute(map, e)
      map.getCanvas().style.cursor = feature || truck || route ? 'pointer' : ''

      const key = feature ? `${feature.properties.routeId}:${feature.properties.index}` : ''
      if (key !== hoverKey) {
        hoverKey = key
        latest.current.onHoverCheckpoint(
          feature ? { routeId: feature.properties.routeId, index: feature.properties.index } : null,
        )
      }
      hoveredTruck.current = truck && !feature ? (truck.properties.routeId as string) : null
      updateTruckPopup()
    })
    map.on('mouseout', () => {
      hoverKey = ''
      hoveredTruck.current = null
      latest.current.onHoverCheckpoint(null)
      updateTruckPopup()
    })
    map.on('click', (e) => {
      const feature = pickCheckpoint(e)
      if (feature) {
        latest.current.onPickCheckpoint({
          routeId: feature.properties.routeId,
          index: feature.properties.index,
        })
        return
      }
      const route = nearestRoute(map, e)
      if (route) latest.current.onSelectRoute(route)
    })
  }

  function updateTruckPopup() {
    const map = mapRef.current
    const { plan: current, timeHours: hours } = latest.current
    const route = current?.routes.find((r) => r.id === hoveredTruck.current)
    if (!map || !current || !route) {
      truckPopupRef.current.remove()
      return
    }
    const truck = truckAt(route, hours)
    truckPopupRef.current
      .setLngLat([truck.lon, truck.lat])
      .setHTML(truckPopup(route, truck, addHours(current.request.departure, hours)))
      .addTo(map)
  }

  // Plan data -> sources (once per plan).
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map) return
    const set = (id: SourceId, data: GeoJSON.FeatureCollection) =>
      (map.getSource(id) as GeoJSONSource).setData(data)
    hoverPopup.current.remove()
    if (!plan) {
      SOURCES.forEach((id) => set(id, EMPTY))
      heatmapRef.current?.setData(null)
      return
    }
    set('routes', routeLines(plan))
    set('segments', riskSegments(plan))
    set('checkpoints', checkpointPoints(plan))
    set('stops', stopPoints(plan))
    set('endpoints', endpoints(plan))
    set('labels', routeLabels(plan))
    heatmapRef.current?.setData(plan.heatmap)
    map.fitBounds(planBounds(plan), {
      padding: latest.current.padding,
      duration: 900,
      maxZoom: 9,
    })
  }, [ready, plan])

  // Selected route -> filters.
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map || !selectedRouteId) return
    applySelection(map, selectedRouteId)
  }, [ready, plan, selectedRouteId])

  // Slider time / heatmap metric -> trucks + heatmap texture.
  useEffect(() => {
    const map = mapRef.current
    const heatmap = heatmapRef.current
    if (!ready || !map || !heatmap || !plan) return
    heatmap.setVisible(heatmapVisible)
    if (heatmapVisible) {
      heatmap.render(frameIndex(plan.heatmap.frame0, plan.request.departure, timeHours), metric)
    }
    const trucks = plan.routes.map((route) => truckAt(route, timeHours))
    ;(map.getSource('trucks') as GeoJSONSource).setData(truckPoints(trucks))
    updateTruckPopup()
  }, [ready, plan, timeHours, metric, heatmapVisible])

  // Hovered checkpoint (from the map or the sidebar list) -> highlight + popup.
  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map || !plan || !hovered) {
      hoverPopup.current.remove()
      return
    }
    const routeIndex = plan.routes.findIndex((r) => r.id === hovered.routeId)
    const route = plan.routes[routeIndex]
    const cp = route?.checkpoints[hovered.index]
    if (!cp) return
    const target = { source: 'checkpoints', id: checkpointFeatureId(routeIndex, cp.index) }
    map.setFeatureState(target, { hover: true })
    hoverPopup.current
      .setLngLat([cp.lon, cp.lat])
      .setHTML(checkpointPopup(route, cp, plan.request.load_weight_lb))
      .addTo(map)
    return () => {
      if (mapRef.current) map.setFeatureState(target, { hover: false })
    }
  }, [ready, plan, hovered])

  useEffect(() => {
    const map = mapRef.current
    if (!ready || !map || !focus) return
    map.easeTo({ center: [focus.lon, focus.lat], zoom: Math.max(map.getZoom(), 7), duration: 700 })
  }, [ready, focus])

  return <div ref={containerRef} className="map" role="region" aria-label="Route map" />
}

/** Route id under the cursor, with a few pixels of slack so thin lines are easy to hit. */
function nearestRoute(map: MlMap, e: MapMouseEvent): string | null {
  const slack = 6
  const box: [PointLike, PointLike] = [
    [e.point.x - slack, e.point.y - slack],
    [e.point.x + slack, e.point.y + slack],
  ]
  const feature = map.queryRenderedFeatures(box, { layers: INTERACTIVE.routes })[0]
  return feature ? (feature.properties.routeId as string) : null
}
