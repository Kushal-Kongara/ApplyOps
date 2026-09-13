import { describe, expect, it } from 'vitest'
import { formatDate, isOverdue, relativeTime, statusLabel, toDateInputValue, visaLabel } from './format'

describe('statusLabel', () => {
  it('renders known statuses with title case and spaces', () => {
    expect(statusLabel('outreach_sent')).toBe('Outreach Sent')
    expect(statusLabel('new')).toBe('New')
  })

  it('falls back to the raw value for an unknown status', () => {
    expect(statusLabel('ghosted')).toBe('ghosted')
  })
})

describe('visaLabel', () => {
  it('renders "Unknown" for null or the unknown sentinel', () => {
    expect(visaLabel(null)).toBe('Unknown')
    expect(visaLabel('unknown')).toBe('Unknown')
  })

  it('title-cases a snake_case signal', () => {
    expect(visaLabel('sponsorship_risk')).toBe('Sponsorship Risk')
    expect(visaLabel('citizenship_or_clearance_required')).toBe('Citizenship Or Clearance Required')
  })
})

describe('formatDate', () => {
  it('returns null for a null input', () => {
    expect(formatDate(null)).toBeNull()
  })

  it('formats a valid ISO date', () => {
    expect(formatDate('2026-09-20T00:00:00Z')).toContain('2026')
  })

  it('falls back to the raw string for unparseable input', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })
})

describe('toDateInputValue', () => {
  it('returns an empty string for null', () => {
    expect(toDateInputValue(null)).toBe('')
  })

  it('returns YYYY-MM-DD for a full ISO datetime', () => {
    expect(toDateInputValue('2026-09-20T15:30:00Z')).toBe('2026-09-20')
  })
})

describe('isOverdue', () => {
  const now = new Date('2026-09-10T00:00:00Z')

  it('is false when there is no follow-up date', () => {
    expect(isOverdue(null, now)).toBe(false)
  })

  it('is true when the date is in the past', () => {
    expect(isOverdue('2026-09-01T00:00:00Z', now)).toBe(true)
  })

  it('is false when the date is in the future', () => {
    expect(isOverdue('2026-09-20T00:00:00Z', now)).toBe(false)
  })
})

describe('relativeTime', () => {
  const now = new Date('2026-09-13T12:00:00Z')

  it('renders "just now" for under a minute', () => {
    expect(relativeTime('2026-09-13T11:59:45Z', now)).toBe('just now')
  })

  it('renders minutes ago', () => {
    expect(relativeTime('2026-09-13T11:48:00Z', now)).toBe('12 minutes ago')
  })

  it('singularizes 1 minute', () => {
    expect(relativeTime('2026-09-13T11:59:00Z', now)).toBe('1 minute ago')
  })

  it('renders hours ago', () => {
    expect(relativeTime('2026-09-13T09:00:00Z', now)).toBe('3 hours ago')
  })

  it('singularizes 1 hour', () => {
    expect(relativeTime('2026-09-13T11:00:00Z', now)).toBe('1 hour ago')
  })

  it('renders "23 hours ago" without rolling over into days', () => {
    expect(relativeTime('2026-09-12T13:00:00Z', now)).toBe('23 hours ago')
  })

  it('renders days ago once past 24 hours', () => {
    expect(relativeTime('2026-09-11T12:00:00Z', now)).toBe('2 days ago')
  })

  it('falls back to the raw string for unparseable input', () => {
    expect(relativeTime('not-a-date', now)).toBe('not-a-date')
  })
})
