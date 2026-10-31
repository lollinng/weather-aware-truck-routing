const HOUR_MS = 3_600_000

export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  // Truckers think in hours; switch to days only for multi-day trips.
  if (hours >= 72) return `${Math.floor(hours / 24)}d ${hours % 24}h`
  if (hours) return minutes ? `${hours}h ${minutes}m` : `${hours}h`
  return `${minutes}m`
}

export function formatHoursOffset(hours: number): string {
  return `+${formatDuration(hours * 3600)}`
}

const dayTime = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
})
const dayTimeZone = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})

/** "Sat 4:15 PM" in the viewer's time zone. */
export function formatClock(value: string | Date): string {
  return dayTime.format(typeof value === 'string' ? new Date(value) : value)
}

export function formatClockLong(value: string | Date): string {
  return dayTimeZone.format(typeof value === 'string' ? new Date(value) : value)
}

export function formatMiles(miles: number): string {
  if (miles === 0) return '0 mi'
  if (miles < 10) return `${miles.toFixed(1)} mi`
  return `${Math.round(miles).toLocaleString()} mi`
}

export function formatNumber(value: number, digits = 0): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function addHours(iso: string, hours: number): Date {
  return new Date(new Date(iso).getTime() + hours * HOUR_MS)
}

/** Value for <input type="datetime-local"> in local time. */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** Next quarter hour from now – a sensible default departure. */
export function nextQuarterHour(now = new Date()): Date {
  const d = new Date(now)
  d.setSeconds(0, 0)
  d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15)
  return d
}
