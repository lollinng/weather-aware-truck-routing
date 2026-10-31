/** WMO weather interpretation codes as returned by Open-Meteo. */
const WMO: Record<number, string> = {
  0: 'Clear',
  1: 'Mostly clear',
  2: 'Partly cloudy',
  3: 'Overcast',
  45: 'Fog',
  48: 'Freezing fog',
  51: 'Light drizzle',
  53: 'Drizzle',
  55: 'Heavy drizzle',
  56: 'Freezing drizzle',
  57: 'Heavy freezing drizzle',
  61: 'Light rain',
  63: 'Rain',
  65: 'Heavy rain',
  66: 'Freezing rain',
  67: 'Heavy freezing rain',
  71: 'Light snow',
  73: 'Snow',
  75: 'Heavy snow',
  77: 'Snow grains',
  80: 'Rain showers',
  81: 'Heavy showers',
  82: 'Violent showers',
  85: 'Snow showers',
  86: 'Heavy snow showers',
  95: 'Thunderstorm',
  96: 'Thunderstorm, hail',
  99: 'Severe thunderstorm, hail',
}

export function describeWeather(code: number | null): string {
  if (code === null) return '—'
  return WMO[code] ?? `Code ${code}`
}

/** Conditions the risk table doesn't cover but a driver should know about. */
export function isIcy(code: number | null): boolean {
  return code === 48 || code === 56 || code === 57 || code === 66 || code === 67
}
