// Thin fetch wrapper around the FastAPI backend. Every function here maps
// to exactly one backend endpoint — no client-side ranking, filtering
// logic beyond what the query params already ask the API to do, or status
// validation duplicated from the backend.

import type {
  ApplicationRecord,
  ApplicationUpdatePayload,
  DashboardResponse,
  FollowUpsResponse,
  JobCard,
  JobDetail,
  JobsQuery,
  LatexSourceResponse,
  RecentResponse,
  ResumeVersionDetail,
  ResumeVersionSummary,
} from './types'

export class ApiError extends Error {
  status: number
  /** Machine-readable error state (e.g. "master_resume_missing",
   * "latex_compiler_unavailable") for endpoints that return a structured
   * `{error, message}` detail — undefined for plain-string error details. */
  code?: string

  constructor(status: number, message: string, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/** Turn a FastAPI error body's `detail` (a plain string, or a structured
 * `{error, message}` object) into a readable message plus an optional code. */
export function parseErrorDetail(detail: unknown, status: number): { message: string; code?: string } {
  if (typeof detail === 'string') return { message: detail }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const record = detail as { message: unknown; error?: unknown }
    return {
      message: typeof record.message === 'string' ? record.message : `Request failed (${status})`,
      code: typeof record.error === 'string' ? record.error : undefined,
    }
  }
  return { message: `Request failed (${status})` }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const { message, code } = parseErrorDetail(body?.detail, response.status)
    throw new ApiError(response.status, message, code)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Build the `/api/jobs` query string from filter state. Pure and exported
 * so it can be unit-tested without a network call. */
export function buildJobsQueryString(query: JobsQuery): string {
  const params = new URLSearchParams()
  if (query.q) params.set('q', query.q)
  if (query.min_score !== undefined) params.set('min_score', String(query.min_score))
  if (query.status) params.set('status', query.status)
  const asString = params.toString()
  return asString ? `?${asString}` : ''
}

export function getDashboard(): Promise<DashboardResponse> {
  return request<DashboardResponse>('/api/dashboard')
}

export function getJobs(query: JobsQuery = {}): Promise<JobCard[]> {
  return request<JobCard[]>(`/api/jobs${buildJobsQueryString(query)}`)
}

export function getJob(jobId: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}`)
}

export function getApplications(status?: string): Promise<ApplicationRecord[]> {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return request<ApplicationRecord[]>(`/api/applications${suffix}`)
}

export function updateApplication(
  jobId: string,
  payload: ApplicationUpdatePayload,
): Promise<ApplicationRecord> {
  return request<ApplicationRecord>(`/api/applications/${encodeURIComponent(jobId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function getFollowUps(): Promise<FollowUpsResponse> {
  return request<FollowUpsResponse>('/api/follow-ups')
}

export interface RecentJobsQuery {
  min_score?: number
  older_limit?: number
  older_offset?: number
}

export function getRecentJobs(query: RecentJobsQuery = {}): Promise<RecentResponse> {
  const params = new URLSearchParams()
  if (query.min_score !== undefined) params.set('min_score', String(query.min_score))
  if (query.older_limit !== undefined) params.set('older_limit', String(query.older_limit))
  if (query.older_offset !== undefined) params.set('older_offset', String(query.older_offset))
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return request<RecentResponse>(`/api/jobs/recent${suffix}`)
}

// --- resumes --------------------------------------------------------------
//
// Generation is always explicitly user-triggered — nothing here is ever
// called automatically (not on job collection, not on a match score, not
// on a scheduler cycle).

export function generateResume(jobId: string): Promise<ResumeVersionDetail> {
  return request<ResumeVersionDetail>(`/api/jobs/${encodeURIComponent(jobId)}/resumes`, { method: 'POST' })
}

export function listJobResumes(jobId: string): Promise<ResumeVersionSummary[]> {
  return request<ResumeVersionSummary[]>(`/api/jobs/${encodeURIComponent(jobId)}/resumes`)
}

export function getResume(resumeId: number): Promise<ResumeVersionDetail> {
  return request<ResumeVersionDetail>(`/api/resumes/${resumeId}`)
}

export function getResumeLatex(resumeId: number): Promise<LatexSourceResponse> {
  return request<LatexSourceResponse>(`/api/resumes/${resumeId}/latex`)
}

export function approveResume(resumeId: number): Promise<ResumeVersionDetail> {
  return request<ResumeVersionDetail>(`/api/resumes/${resumeId}/approve`, { method: 'POST' })
}

/** Direct URL for the compiled PDF — used as an `<iframe>`/`<object>` `src`
 * and for the "Download PDF" link, never fetched and re-wrapped here. */
export function resumePdfUrl(resumeId: number): string {
  return `/api/resumes/${resumeId}/pdf`
}
