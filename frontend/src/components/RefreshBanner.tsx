import { relativeTime } from '../format'
import type { RefreshSummary } from '../types'

interface Props {
  refresh: RefreshSummary | null
}

function capitalize(value: string): string {
  return value.length === 0 ? value : value[0].toUpperCase() + value.slice(1)
}

/** Compact "when did the backend last refresh, and what did it find"
 * indicator. Purely a display of `refresh_runs` data the backend already
 * computed — no re-scoring, no re-bucketing, nothing recalculated here. */
export function RefreshBanner({ refresh }: Props) {
  if (!refresh) {
    return <div className="refresh-banner refresh-banner--muted">No refresh has run yet.</div>
  }

  const failed = refresh.status !== 'success'

  return (
    <div className={failed ? 'refresh-banner refresh-banner--warn' : 'refresh-banner'}>
      <div className="refresh-banner__line">
        Last refreshed: {relativeTime(refresh.finished_at)}
        {failed && <span className="refresh-banner__status"> — {capitalize(refresh.status)}</span>}
      </div>
      <div className="refresh-banner__stats">
        {refresh.jobs_new} new job{refresh.jobs_new === 1 ? '' : 's'} · {refresh.high_priority_new} high priority ·{' '}
        {refresh.review_new} review
      </div>
      {refresh.error_message && <div className="refresh-banner__error">{refresh.error_message}</div>}
    </div>
  )
}
