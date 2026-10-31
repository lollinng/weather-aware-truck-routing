import { useEffect, useLayoutEffect, useRef } from 'react'

/**
 * Advances ``hours`` with requestAnimationFrame while ``playing``. Uses real frame deltas, so
 * playback speed is independent of the display's refresh rate, and stops at ``maxHours``.
 */
export function usePlayback(
  playing: boolean,
  hours: number,
  setHours: (hours: number) => void,
  { hoursPerSecond, maxHours, onEnd }: { hoursPerSecond: number; maxHours: number; onEnd: () => void },
): void {
  const state = useRef({ hours, setHours, onEnd })
  useLayoutEffect(() => {
    state.current = { hours, setHours, onEnd }
  })

  useEffect(() => {
    if (!playing) return
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000) // clamp after a backgrounded tab
      last = now
      const next = Math.min(maxHours, state.current.hours + dt * hoursPerSecond)
      state.current.hours = next
      state.current.setHours(next)
      if (next >= maxHours) state.current.onEnd()
      else frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, hoursPerSecond, maxHours])
}
