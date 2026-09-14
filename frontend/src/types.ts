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

// --- Job Detail + resume tailoring ---------------------------------------

export interface JobDetail extends JobCard {
  description: string
  unmatched_skills: string[]
}

export interface TailoringAnalysis {
  strong_matches: string[]
  supported_but_underemphasized: string[]
  unsupported_requirements: string[]
  selected_experience: string[]
  selected_projects: string[]
}

export type ResumeCompilerStatus = 'not_attempted' | 'compiled' | 'unavailable' | 'failed'
export type ResumeStatus = 'draft' | 'approved' | 'used'
export type ResumeGenerationMode = 'deterministic' | 'llm_enhanced'
export type RewriteValidationStatus = 'accepted' | 'rejected' | 'error'

export interface ResumeVersionSummary {
  id: number
  job_unique_key: string
  version: number
  status: ResumeStatus
  compiler_status: ResumeCompilerStatus
  page_count: number | null
  generation_mode: ResumeGenerationMode
  llm_provider: string | null
  llm_model: string | null
  rewrite_attempted: number
  rewrite_accepted: number
  rewrite_rejected: number
  created_at: string
  updated_at: string
  approved_at: string | null
}

export interface RewriteAttempt {
  evidence_id: string
  original_text: string
  rewritten_text: string | null
  validation_status: RewriteValidationStatus
  validation_reasons: string[]
  provider: string
  model: string
}

export interface ResumeVersionDetail extends ResumeVersionSummary {
  compile_log: string | null
  tailoring_analysis: TailoringAnalysis
  rewrite_provenance: RewriteAttempt[]
}

export interface LatexSourceResponse {
  latex_source: string
}

export interface LLMStatus {
  provider: string
  configured: boolean
  reachable: boolean
  model: string | null
  error: string | null
  available_models: string[] | null
}

// --- application preparation ---------------------------------------------

export type QuestionType = 'text' | 'textarea' | 'number' | 'boolean' | 'single_select' | 'multi_select' | 'date'

export type QuestionCategory =
  | 'identity' | 'contact' | 'work_authorization' | 'sponsorship' | 'location' | 'relocation'
  | 'availability' | 'salary' | 'education' | 'experience' | 'skills'
  | 'company_motivation' | 'role_motivation' | 'behavioral' | 'demographic_optional' | 'other'

export type AnswerSource =
  | 'applicant_profile' | 'master_resume' | 'approved_resume'
  | 'generated_from_evidence' | 'user_input_required' | 'user_edited'

export type PreparationStatus = 'draft' | 'needs_input' | 'ready' | 'used'

export interface ApplicationAnswer {
  id: number
  preparation_id: number
  question_id: string
  question_text: string
  question_type: QuestionType
  category: QuestionCategory
  required: boolean
  answer: string | null
  answer_source: AnswerSource
  needs_user_input: boolean
  evidence_ids: string[]
  user_edited: boolean
  created_at: string
  updated_at: string
}

export interface ApplicationPreparationSummary {
  id: number
  job_unique_key: string
  resume_version_id: number | null
  status: PreparationStatus
  created_at: string
  updated_at: string
}

export interface ApplicationPreparationDetail extends ApplicationPreparationSummary {
  answers: ApplicationAnswer[]
}

export interface AddQuestionPayload {
  question_text: string
  question_type: QuestionType
  category: QuestionCategory
  required?: boolean
}

// --- ATS form filling ------------------------------------------------------

export type FieldFillStatus = 'filled' | 'needs_input' | 'skipped' | 'unsupported'

export interface FilledField {
  label: string
  status: FieldFillStatus
  value: string | null
  reason: string
}

export interface FillApplicationResponse {
  ats: string | null
  application_url: string
  fields: FilledField[]
  resume_uploaded: boolean
  resume_error: string | null
  error: string | null
}
