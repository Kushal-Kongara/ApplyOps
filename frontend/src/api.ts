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
  JobsQuery,
  RecentResponse,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const message = body?.detail ?? `Request failed (${response.status})`
    throw new ApiError(response.status, message)
  }

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

export function getJob(jobId: string): Promise<JobCard> {
  return request<JobCard>(`/api/jobs/${encodeURIComponent(jobId)}`)
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
