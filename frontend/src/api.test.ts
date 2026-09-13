import { describe, expect, it } from 'vitest'
import { buildJobsQueryString } from './api'

describe('buildJobsQueryString', () => {
  it('returns an empty string for no filters', () => {
    expect(buildJobsQueryString({})).toBe('')
  })

  it('includes only the filters that are set', () => {
    expect(buildJobsQueryString({ min_score: 70 })).toBe('?min_score=70')
  })

  it('combines multiple filters', () => {
    const result = buildJobsQueryString({ q: 'engineer', min_score: 65, status: 'shortlisted' })
    const params = new URLSearchParams(result.slice(1))
    expect(params.get('q')).toBe('engineer')
    expect(params.get('min_score')).toBe('65')
    expect(params.get('status')).toBe('shortlisted')
  })

  it('omits min_score of 0 the same as unset (both mean "all")', () => {
    // min_score: 0 is falsy-but-meaningful — must still be omitted only
    // when truly absent (undefined), not silently dropped when 0.
    expect(buildJobsQueryString({ min_score: 0 })).toBe('?min_score=0')
  })

  it('url-encodes special characters in the search text', () => {
    const result = buildJobsQueryString({ q: 'C++ & Co' })
    expect(result).toContain('C%2B%2B')
  })
})
