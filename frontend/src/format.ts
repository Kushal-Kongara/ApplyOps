// Pure display-formatting helpers — no fetching, no state. Kept separate
// so they're trivially unit-testable.

import type { ApplicationStatus } from './types'

const STATUS_LABELS: Record<ApplicationStatus, string> = {
  new: 'New',
  shortlisted: 'Shortlisted',
  applying: 'Applying',
  applied: 'Applied',
  outreach_sent: 'Outreach Sent',
  interviewing: 'Interviewing',
  rejected: 'Rejected',
  offer: 'Offer',
  skipped: 'Skipped',
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as ApplicationStatus] ?? status
}

export function visaLabel(signal: string | null): string {
  if (!signal || signal === 'unknown') return 'Unknown'
  return signal
    .split('_')
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(' ')
}

/** "2026-09-20T00:00:00Z" -> "Sep 20, 2026". Falls back to the raw string
 * if it isn't parseable, rather than showing "Invalid Date". */
export function formatDate(value: string | null): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Local input[type=date] wants YYYY-MM-DD; the API returns full ISO. */
export function toDateInputValue(value: string | null): string {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toISOString().slice(0, 10)
}

export function isOverdue(nextFollowUpAt: string | null, now: Date = new Date()): boolean {
  if (!nextFollowUpAt) return false
  const parsed = new Date(nextFollowUpAt)
  return !Number.isNaN(parsed.getTime()) && parsed <= now
}

/** "12 minutes ago" / "1 hour ago" / "3 hours ago" / "2 days ago".
 *
 * Display only — the backend, not this function, decides which 2-hour
 * bucket a job belongs to. This never rounds an elapsed time up into the
 * next bucket's wording; it only describes the timestamp for a human.
 */
export function relativeTime(value: string, now: Date = new Date()): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value

  const seconds = Math.max(0, Math.round((now.getTime() - parsed.getTime()) / 1000))
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (seconds < 60) return 'just now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  return `${days} day${days === 1 ? '' : 's'} ago`
}
