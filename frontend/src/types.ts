// Mirrors backend/app/api.py's Pydantic response models exactly — one
// shape per JSON body the API actually returns. Keep these in sync with
// the backend by hand; there's no code generation step in this phase.

export type ApplicationStatus =
  | 'new'
  | 'shortlisted'
  | 'applying'
  | 'applied'
  | 'outreach_sent'
  | 'interviewing'
  | 'rejected'
  | 'offer'
  | 'skipped'

export const APPLICATION_STATUSES: ApplicationStatus[] = [
  'new',
  'shortlisted',
  'applying',
  'applied',
  'outreach_sent',
  'interviewing',
  'rejected',
  'offer',
  'skipped',
]

// One card shape for every endpoint that returns a scored job — dashboard
// sections, /api/jobs, a single job, and /api/follow-ups.
export interface JobCard {
  job_unique_key: string
  kind: 'new' | 'follow_up'
  title: string
  company: string
  location: string
  source: string | null
  application_url: string
  status: ApplicationStatus
  total_score: number | null
  title_score: number | null
  skills_score: number | null
  location_score: number | null
  seniority_score: number | null
  product_score: number | null
  visa_signal: string | null
  visa_evidence: string | null
  matched_skills: string[]
  next_follow_up_at: string | null
  notes: string | null
}

export interface DashboardSummary {
  high_priority: number
  review: number
  follow_ups_due: number
  applications_total: number
}

export interface RefreshSummary {
  started_at: string
  finished_at: string
  status: 'success' | 'partial' | 'failed'
  jobs_new: number
  jobs_updated: number
  high_priority_new: number
  review_new: number
  error_message: string | null
}

export interface DashboardResponse {
  summary: DashboardSummary
  high_priority: JobCard[]
  review_candidates: JobCard[]
  follow_ups: JobCard[]
  last_refresh: RefreshSummary | null
}

export interface FollowUpsResponse {
  due: JobCard[]
  upcoming: JobCard[]
}

// A JobCard plus when it was discovered — only the Recent timeline needs
// this extra field.
export interface RecentJobCard extends JobCard {
  first_seen_at: string
}

export interface RecentBucket {
  key: string
  label: string
  min_hours: number
  max_hours: number | null
  count: number
  jobs: RecentJobCard[]
}

export interface RecentSummary {
  last_24h: number
  high_priority: number
  review: number
  older_than_24h: number
}

export interface RecentResponse {
  generated_at: string
  summary: RecentSummary
  buckets: RecentBucket[]
  older: RecentBucket
}

export interface ApplicationRecord {
  job_unique_key: string
  title: string
  company: string
  location: string
  application_url: string
  status: ApplicationStatus
  applied_at: string | null
  last_action_at: string
  next_follow_up_at: string | null
  notes: string
  created_at: string
  updated_at: string
}

export interface ApplicationUpdatePayload {
  status?: ApplicationStatus
  notes?: string
  next_follow_up_at?: string | null
}

export interface JobsQuery {
  q?: string
  min_score?: number
  status?: ApplicationStatus
}
