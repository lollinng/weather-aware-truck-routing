import { useState } from 'react'

import { searchPlaces } from '../api/client'
import type { Place, PlanRequest, SamplingInterval } from '../api/types'
import { nextQuarterHour, toLocalInputValue } from '../lib/format'
import { PlaceInput, type PlaceValue } from './PlaceInput'

const INTERVALS: SamplingInterval[] = [10, 25, 50]
const MAX_DAYS_AHEAD = 7

const PRESETS: { name: string; origin: Place; destination: Place }[] = [
  {
    name: 'Chicago → Denver',
    origin: { label: 'Chicago, Illinois', lat: 41.8781, lon: -87.6298 },
    destination: { label: 'Denver, Colorado', lat: 39.7392, lon: -104.9903 },
  },
  {
    name: 'Seattle → Salt Lake City',
    origin: { label: 'Seattle, Washington', lat: 47.6062, lon: -122.3321 },
    destination: { label: 'Salt Lake City, Utah', lat: 40.7608, lon: -111.891 },
  },
  {
    name: 'Dallas → Atlanta',
    origin: { label: 'Dallas, Texas', lat: 32.7767, lon: -96.797 },
    destination: { label: 'Atlanta, Georgia', lat: 33.749, lon: -84.388 },
  },
]

interface TripFormProps {
  loading: boolean
  fieldErrors: Record<string, string>
  onSubmit: (request: PlanRequest) => void
}

const fromPlace = (place: Place): PlaceValue => ({ text: place.label, place })

/** Resolve free text the user typed but didn't pick from the list. */
async function resolve(value: PlaceValue): Promise<Place | null> {
  if (value.place) return value.place
  if (value.text.trim().length < 2) return null
  const [best] = await searchPlaces(value.text.trim())
  return best ?? null
}

export function TripForm({ loading, fieldErrors, onSubmit }: TripFormProps) {
  const [origin, setOrigin] = useState<PlaceValue>(fromPlace(PRESETS[0].origin))
  const [destination, setDestination] = useState<PlaceValue>(fromPlace(PRESETS[0].destination))
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextQuarterHour()))
  const [load, setLoad] = useState('42000')
  const [interval, setSamplingInterval] = useState<SamplingInterval>(25)
  const [hos, setHos] = useState(true)
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({})
  const [resolving, setResolving] = useState(false)

  const errors = { ...fieldErrors, ...localErrors }
  const [now] = useState(() => new Date())
  const maxDeparture = new Date(now.getTime() + MAX_DAYS_AHEAD * 86_400_000)
  const loadLb = Number(load)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const problems: Record<string, string> = {}
    const departureDate = new Date(departure)
    if (Number.isNaN(departureDate.getTime())) problems.departure = 'Pick a departure time.'
    if (!Number.isFinite(loadLb) || loadLb < 0 || loadLb > 80_000) {
      problems.load_weight_lb = 'Enter a load between 0 and 80,000 lb.'
    }
    setResolving(true)
    let o: Place | null = null
    let d: Place | null = null
    try {
      ;[o, d] = await Promise.all([resolve(origin), resolve(destination)])
    } catch {
      problems.origin = 'Place search is unavailable right now.'
    } finally {
      setResolving(false)
    }
    if (!o) problems.origin ??= 'Choose an origin from the suggestions.'
    if (!d) problems.destination = 'Choose a destination from the suggestions.'
    setLocalErrors(problems)
    if (Object.keys(problems).length || !o || !d) return
    if (!origin.place) setOrigin(fromPlace(o))
    if (!destination.place) setDestination(fromPlace(d))
    onSubmit({
      origin: o,
      destination: d,
      departure: departureDate.toISOString(),
      load_weight_lb: Math.round(loadLb),
      interval_miles: interval,
      hos,
    })
  }

  const busy = loading || resolving

  return (
    <form className="trip-form" onSubmit={handleSubmit} noValidate>
      <div className="trip-form__places">
        <PlaceInput
          label="Origin"
          marker="origin"
          value={origin}
          onChange={setOrigin}
          placeholder="City or address"
          error={errors.origin ?? errors['origin.lat']}
        />
        <button
          type="button"
          className="icon-button trip-form__swap"
          title="Swap origin and destination"
          aria-label="Swap origin and destination"
          onClick={() => {
            setOrigin(destination)
            setDestination(origin)
          }}
        >
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d="M7 4v13m0 0-3-3m3 3 3-3M17 20V7m0 0-3 3m3-3 3 3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <PlaceInput
          label="Destination"
          marker="destination"
          value={destination}
          onChange={setDestination}
          placeholder="City or address"
          error={errors.destination ?? errors['destination.lat']}
        />
      </div>

      <div className="trip-form__presets" aria-label="Example trips">
        {PRESETS.map((preset) => (
          <button
            key={preset.name}
            type="button"
            className="chip"
            onClick={() => {
              setOrigin(fromPlace(preset.origin))
              setDestination(fromPlace(preset.destination))
            }}
          >
            {preset.name}
          </button>
        ))}
      </div>

      <div className="trip-form__row">
        <div className="field">
          <label htmlFor="departure" className="field__label">
            Departure
          </label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            min={toLocalInputValue(now)}
            max={toLocalInputValue(maxDeparture)}
            onChange={(e) => setDeparture(e.target.value)}
            aria-invalid={Boolean(errors.departure)}
            required
          />
          {errors.departure && <p className="field__error">{errors.departure}</p>}
        </div>
        <div className="field">
          <label htmlFor="load" className="field__label">
            Load weight
          </label>
          <div className="input-suffix">
            <input
              id="load"
              type="number"
              inputMode="numeric"
              min={0}
              max={80000}
              step={500}
              value={load}
              onChange={(e) => setLoad(e.target.value)}
              aria-invalid={Boolean(errors.load_weight_lb)}
              aria-describedby="load-hint"
            />
            <span>lb</span>
          </div>
          {errors.load_weight_lb && <p className="field__error">{errors.load_weight_lb}</p>}
        </div>
      </div>
      <p id="load-hint" className="field__hint">
        {loadLb > 40_000
          ? 'Over 40,000 lb: 35–44 mph wind is Severe, 45+ mph is No Travel.'
          : loadLb > 30_000
            ? 'Over 30,000 lb: 45–54 mph wind is No Travel.'
            : 'Heavier loads (>30k, >40k lb) tighten the wind limits.'}
      </p>

      <div className="trip-form__row trip-form__row--options">
        <fieldset className="field">
          <legend className="field__label">Weather every</legend>
          <div className="segmented" role="radiogroup">
            {INTERVALS.map((value) => (
              <label key={value} className={interval === value ? 'is-selected' : undefined}>
                <input
                  type="radio"
                  name="interval"
                  value={value}
                  checked={interval === value}
                  onChange={() => setSamplingInterval(value)}
                />
                {value} mi
              </label>
            ))}
          </div>
        </fieldset>
        <label className="toggle" title="FMCSA hours of service: 30-min break after 8 h driving, 10-h rest after 11 h">
          <input type="checkbox" checked={hos} onChange={(e) => setHos(e.target.checked)} />
          <span className="toggle__track" aria-hidden="true" />
          <span className="toggle__text">
            Hours-of-service breaks
            <small>30 min after 8 h, 10 h rest after 11 h</small>
          </span>
        </label>
      </div>

      <button type="submit" className="button button--primary" disabled={busy}>
        {busy ? (
          <>
            <span className="spinner" aria-hidden="true" /> Planning…
          </>
        ) : (
          'Plan routes'
        )}
      </button>
    </form>
  )
}

