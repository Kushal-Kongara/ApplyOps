import type { ReactNode } from 'react'

interface Props {
  loading: boolean
  error: string | null
  isEmpty?: boolean
  emptyMessage?: string
  children: ReactNode
}

/** Consistent loading / error / empty handling for any data-driven section. */
export function AsyncSection({ loading, error, isEmpty, emptyMessage, children }: Props) {
  if (loading) {
    return <div className="state state-loading">Loading…</div>
  }
  if (error) {
    return (
      <div className="state state-error">
        <strong>Couldn't load this.</strong>
        <span>{error}</span>
      </div>
    )
  }
  if (isEmpty) {
    return <div className="state state-empty">{emptyMessage ?? 'Nothing here yet.'}</div>
  }
  return <>{children}</>
}
