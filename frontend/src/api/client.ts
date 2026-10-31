import type { ApiErrorBody, Place, PlanRequest, PlanResponse } from './types'

/**
 * Empty when Django serves the frontend (same origin). For a static deployment such as
 * GitHub Pages, set VITE_API_BASE_URL at build time to the API's origin.
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly fields: Record<string, string>

  constructor(status: number, message: string, fields: Record<string, string> = {}) {
    super(message)
    this.status = status
    this.fields = fields
  }
}

/** Flattens DRF validation errors ({field: [msg]} or nested) into {field: msg}. */
export function flattenErrors(body: unknown, prefix = ''): Record<string, string> {
  if (!body || typeof body !== 'object') return {}
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    const name = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out[name] = value
    else if (Array.isArray(value) && typeof value[0] === 'string') out[name] = value[0]
    else if (value && typeof value === 'object') Object.assign(out, flattenErrors(value, name))
  }
  return out
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new ApiError(0, 'Could not reach the server. Check your connection and try again.')
  }
  if (response.ok) return (await response.json()) as T

  let body: ApiErrorBody = {}
  try {
    body = (await response.json()) as ApiErrorBody
  } catch {
    // Non-JSON error page (e.g. a proxy timeout) – fall through to a generic message.
  }
  const fields = response.status === 400 ? flattenErrors(body) : {}
  const message =
    body.detail ??
    (response.status === 400
      ? 'Please check the highlighted fields.'
      : response.status === 429
        ? 'Too many requests – please wait a moment and try again.'
        : `Request failed (HTTP ${response.status}).`)
  throw new ApiError(response.status, message, fields)
}

export function planTrip(body: PlanRequest, signal?: AbortSignal): Promise<PlanResponse> {
  return request<PlanResponse>('/api/plan', { method: 'POST', body: JSON.stringify(body), signal })
}

/** Fire-and-forget request that wakes a sleeping free-tier backend while the user types. */
export function warmUp(): void {
  fetch(`${API_BASE}/api/health`).catch(() => undefined)
}

export async function searchPlaces(query: string, signal?: AbortSignal): Promise<Place[]> {
  const params = new URLSearchParams({ q: query })
  const data = await request<{ results: Place[] }>(`/api/geocode?${params}`, { signal })
  return data.results
}
