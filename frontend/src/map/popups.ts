import type { Checkpoint, RouteOption } from '../api/types'
import { formatClock, formatHoursOffset, formatNumber } from '../lib/format'
import { FACTOR_LABEL, RISK_COLOR, RISK_LABEL } from '../lib/risk'
import { describeWeather, isIcy } from '../lib/weatherCodes'
import type { TruckPosition } from './geojson'

const escapeHtml = (value: string) =>
  value.replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`)

const row = (label: string, value: string) =>
  `<div class="popup__row"><span>${label}</span><strong>${value}</strong></div>`

export function checkpointPopup(route: RouteOption, cp: Checkpoint, loadLb: number): string {
  const level = cp.risk?.level ?? 'unknown'
  const drivers = cp.risk?.drivers.map((d) => FACTOR_LABEL[d]).join(' + ')
  const w = cp.weather
  const lines = [
    `<div class="popup__title">${escapeHtml(route.name)} · mile ${formatNumber(cp.mile)}</div>`,
    `<div class="popup__eta">${formatClock(cp.eta)} <span>${formatHoursOffset(cp.hours_from_departure)}</span></div>`,
    `<div class="popup__risk" style="--chip:${RISK_COLOR[level]}">${RISK_LABEL[level]}${drivers ? ` · ${drivers}` : ''}</div>`,
  ]
  if (w) {
    lines.push(
      row('Wind', `${formatNumber(w.wind_mph)} mph${w.gust_mph !== null ? ` <em>gust ${formatNumber(w.gust_mph)}</em>` : ''}`),
      row('Rain', `${w.rain_in_hr.toFixed(2)} in/hr`),
      row('Snow', `${w.snow_in_hr.toFixed(2)} in/hr`),
      row('Conditions', `${describeWeather(w.weather_code)}${w.temp_f !== null ? `, ${w.temp_f}°F` : ''}`),
    )
    if (cp.risk?.load_adjusted) {
      lines.push(
        `<div class="popup__note">${formatNumber(loadLb)} lb load raises wind risk to ${RISK_LABEL[cp.risk.wind]}.</div>`,
      )
    }
    if (isIcy(w.weather_code)) {
      lines.push('<div class="popup__note">Icing possible – not covered by the risk table.</div>')
    }
  } else {
    lines.push('<div class="popup__note">No forecast available for this time.</div>')
  }
  return lines.join('')
}

const STATE_LABEL: Record<string, string> = {
  D: 'Driving',
  B: 'On 30-min break',
  R: 'On 10-h rest',
  A: 'Arrived',
}

export function truckPopup(route: RouteOption, truck: TruckPosition, at: Date): string {
  return [
    `<div class="popup__title">${escapeHtml(route.name)} truck</div>`,
    `<div class="popup__eta">${formatClock(at)}</div>`,
    row('Status', STATE_LABEL[truck.state] ?? '—'),
    row('Position', `mile ${formatNumber(truck.mile)} of ${formatNumber(route.distance_mi)}`),
  ].join('')
}
