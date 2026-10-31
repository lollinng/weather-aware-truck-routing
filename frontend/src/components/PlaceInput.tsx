import { useEffect, useId, useRef, useState } from 'react'

import { searchPlaces } from '../api/client'
import type { Place } from '../api/types'
import { useDebouncedValue } from '../hooks/useDebouncedValue'

export interface PlaceValue {
  text: string
  place: Place | null
}

interface PlaceInputProps {
  label: string
  value: PlaceValue
  onChange: (value: PlaceValue) => void
  placeholder?: string
  error?: string
  marker: 'origin' | 'destination'
}

const MIN_QUERY = 3

/** Address/city autocomplete (ARIA combobox) backed by /api/geocode. */
export function PlaceInput({ label, value, onChange, placeholder, error, marker }: PlaceInputProps) {
  const id = useId()
  const listId = `${id}-list`
  const [open, setOpen] = useState(false)
  const [found, setFound] = useState<{ query: string; places: Place[] }>({ query: '', places: [] })
  const [active, setActive] = useState(0)
  const query = useDebouncedValue(value.place ? '' : value.text.trim(), 250)
  const blurTimer = useRef<number>(0)

  // Results are only valid for the query they were fetched for; anything else is derived.
  const searching = query.length >= MIN_QUERY
  const results = searching && found.query === query ? found.places : []
  const loading = searching && found.query !== query

  useEffect(() => {
    if (query.length < MIN_QUERY) return
    const controller = new AbortController()
    searchPlaces(query, controller.signal)
      .then((places) => {
        setFound({ query, places })
        setActive(0)
      })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') setFound({ query, places: [] })
      })
    return () => controller.abort()
  }, [query])

  const choose = (place: Place) => {
    onChange({ text: place.label, place })
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (i + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (i - 1 + results.length) % results.length)
    } else if (e.key === 'Enter' && results[active]) {
      e.preventDefault()
      choose(results[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const showList = open && !value.place && results.length > 0

  return (
    <div className={`field place-input place-input--${marker}`}>
      <label htmlFor={id} className="field__label">
        {label}
      </label>
      <div className="place-input__control">
        <span className="place-input__marker" aria-hidden="true" />
        <input
          id={id}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={listId}
          aria-activedescendant={showList ? `${listId}-${active}` : undefined}
          aria-invalid={Boolean(error)}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={value.text}
          onChange={(e) => {
            onChange({ text: e.target.value, place: null })
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            blurTimer.current = window.setTimeout(() => setOpen(false), 120)
          }}
          onKeyDown={onKeyDown}
        />
        {loading && <span className="place-input__spinner" aria-hidden="true" />}
      </div>
      {showList && (
        <ul id={listId} role="listbox" className="place-input__list">
          {results.map((place, i) => (
            <li
              key={`${place.label}-${place.lat}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'is-active' : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => {
                window.clearTimeout(blurTimer.current)
                choose(place)
              }}
            >
              {place.label}
            </li>
          ))}
        </ul>
      )}
      {error && <p className="field__error">{error}</p>}
    </div>
  )
}
