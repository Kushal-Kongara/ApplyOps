import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildJobsQueryString, generateResume, parseErrorDetail, resumePdfUrl } from './api'

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

describe('resumePdfUrl', () => {
  it('builds the direct PDF endpoint path for a resume id', () => {
    expect(resumePdfUrl(42)).toBe('/api/resumes/42/pdf')
  })
})

describe('generateResume', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function stubFetch() {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({}),
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('defaults to deterministic mode when none is given', async () => {
    const fetchMock = stubFetch()
    await generateResume('greenhouse:acme:1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/jobs/greenhouse%3Aacme%3A1/resumes')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ mode: 'deterministic' })
  })

  it('sends the requested mode explicitly', async () => {
    const fetchMock = stubFetch()
    await generateResume('greenhouse:acme:1', 'llm_enhanced')
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init.body)).toEqual({ mode: 'llm_enhanced' })
  })

  it('url-encodes the job id', async () => {
    const fetchMock = stubFetch()
    await generateResume('lever:acme:has spaces')
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/jobs/lever%3Aacme%3Ahas%20spaces/resumes')
  })
})

describe('parseErrorDetail', () => {
  it('passes a plain string detail through as the message with no code', () => {
    expect(parseErrorDetail('No job found.', 404)).toEqual({ message: 'No job found.', code: undefined })
  })

  it('extracts message and error code from a structured detail', () => {
    const result = parseErrorDetail({ error: 'master_resume_missing', message: 'No master resume found.' }, 409)
    expect(result).toEqual({ message: 'No master resume found.', code: 'master_resume_missing' })
  })

  it('falls back to a generic message when detail is missing or unrecognized', () => {
    expect(parseErrorDetail(null, 500)).toEqual({ message: 'Request failed (500)' })
    expect(parseErrorDetail(undefined, 500)).toEqual({ message: 'Request failed (500)' })
    expect(parseErrorDetail({ unexpected: true }, 500)).toEqual({ message: 'Request failed (500)' })
  })
})
