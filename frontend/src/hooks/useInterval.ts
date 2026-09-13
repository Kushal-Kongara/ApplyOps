import { useEffect, useRef } from 'react'

/** Calls `callback` every `delayMs` while mounted. Used for the periodic
 * "read the latest backend data" poll (Today/Recent pages) — this is the
 * *only* thing the frontend automatically triggers on a timer. It never
 * triggers job collection itself: the scheduler (a separate backend
 * process, see `app/scheduler.py`) is what actually refreshes data every
 * 2 hours; the browser only re-reads whatever the backend already has. */
export function useInterval(callback: () => void, delayMs: number): void {
  const savedCallback = useRef(callback)
  savedCallback.current = callback

  useEffect(() => {
    const id = setInterval(() => savedCallback.current(), delayMs)
    return () => clearInterval(id)
  }, [delayMs])
}
