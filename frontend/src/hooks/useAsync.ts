import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api'

interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

/** Runs `fetcher` on mount and whenever `deps` change, exposing
 * loading/error/data state plus a manual `reload()` for after a mutation
 * (e.g. a status change) or a background poll, so the page can refresh
 * without a full reload.
 *
 * `loading` is only ever true before the *first* successful load — a
 * `reload()` (mutation or poll) keeps showing the previous data until the
 * new data arrives, rather than flashing back to a loading state the user
 * has already seen data past.
 */
export function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)
  const hasLoadedOnce = useRef(false)

  const reload = useCallback(() => setReloadToken((token) => token + 1), [])

  useEffect(() => {
    let cancelled = false
    if (!hasLoadedOnce.current) {
      setLoading(true)
    }
    setError(null)

    fetcher()
      .then((result) => {
        if (!cancelled) {
          hasLoadedOnce.current = true
          setData(result)
          setLoading(false)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof ApiError ? err.message : 'Something went wrong. Is the API running?'
          setError(message)
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken])

  return { data, loading, error, reload }
}
