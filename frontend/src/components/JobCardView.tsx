import { useState } from 'react'
import { updateApplication } from '../api'
import { formatDate, relativeTime, statusLabel, toDateInputValue, visaLabel } from '../format'
import type { ApplicationStatus, JobCard } from '../types'
import { APPLICATION_STATUSES } from '../types'

interface Props {
  job: JobCard
  /** Called after a successful status/mark-applied change, so the parent
   * page can refetch its list — this component never re-ranks or filters
   * anything itself. */
  onChanged: () => void
  /** Show the follow-up date editor (set/clear) — used on the Follow-ups page. */
  showFollowUpEditor?: boolean
  /** ISO timestamp of first discovery — shown as "Discovered N ago" when
   * given (the Recent page). Bucket placement already happened on the
   * backend; this is display formatting only. */
  discoveredAt?: string
}

function ScoreRow({ label, value, max }: { label: string; value: number | null; max: number }) {
  return (
    <div className="score-row">
      <span className="score-row__label">{label}</span>
      <span className="score-row__value">
        {value ?? '—'}/{max}
      </span>
    </div>
  )
}

export function JobCardView({ job, onChanged, showFollowUpEditor, discoveredAt }: Props) {
  const [busy, setBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [followUpDraft, setFollowUpDraft] = useState(() => toDateInputValue(job.next_follow_up_at))

  async function apply(payload: Parameters<typeof updateApplication>[1]) {
    setBusy(true)
    setErrorMessage(null)
    try {
      await updateApplication(job.job_unique_key, payload)
      onChanged()
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Update failed.')
    } finally {
      setBusy(false)
    }
  }

  const changeStatus = (status: ApplicationStatus) => apply({ status })
  const saveFollowUp = () => apply({ next_follow_up_at: followUpDraft || null })
  const clearFollowUp = () => {
    setFollowUpDraft('')
    apply({ next_follow_up_at: null })
  }

  const followUp = formatDate(job.next_follow_up_at)

  return (
    <article className="job-card">
      <div className="job-card__score" aria-label="Match score">
        {job.total_score ?? '—'}
      </div>

      <div className="job-card__body">
        <header className="job-card__header">
          <h3 className="job-card__title">{job.title}</h3>
          <div className="job-card__company">{job.company}</div>
          <div className="job-card__location">{job.location || 'Location unknown'}</div>
          {discoveredAt && <div className="job-card__discovered">Discovered {relativeTime(discoveredAt)}</div>}
        </header>

        {job.matched_skills.length > 0 && (
          <div className="job-card__skills">
            {job.matched_skills.map((skill) => (
              <span className="skill-tag" key={skill}>
                {skill}
              </span>
            ))}
          </div>
        )}

        <div className="job-card__breakdown">
          <ScoreRow label="Title" value={job.title_score} max={35} />
          <ScoreRow label="Skills" value={job.skills_score} max={30} />
          <ScoreRow label="Location" value={job.location_score} max={15} />
          <ScoreRow label="Seniority" value={job.seniority_score} max={10} />
          <ScoreRow label="Product" value={job.product_score} max={10} />
        </div>

        <div className="job-card__meta-row">
          <span className="visa-pill">Visa: {visaLabel(job.visa_signal)}</span>
          {job.kind === 'follow_up' && followUp && (
            <span className="follow-up-pill">Follow-up: {followUp}</span>
          )}
        </div>

        <div className="job-card__status-row">
          <label htmlFor={`status-${job.job_unique_key}`}>Status</label>
          <select
            id={`status-${job.job_unique_key}`}
            value={job.status}
            disabled={busy}
            onChange={(event) => changeStatus(event.target.value as ApplicationStatus)}
          >
            {APPLICATION_STATUSES.map((status) => (
              <option key={status} value={status}>
                {statusLabel(status)}
              </option>
            ))}
          </select>
        </div>

        {showFollowUpEditor && (
          <div className="job-card__followup-row">
            <label htmlFor={`followup-${job.job_unique_key}`}>Follow-up date</label>
            <input
              id={`followup-${job.job_unique_key}`}
              type="date"
              value={followUpDraft}
              disabled={busy}
              onChange={(event) => setFollowUpDraft(event.target.value)}
            />
            <button type="button" className="btn btn--secondary btn--small" disabled={busy} onClick={saveFollowUp}>
              Save
            </button>
            {job.next_follow_up_at && (
              <button type="button" className="btn btn--ghost btn--small" disabled={busy} onClick={clearFollowUp}>
                Clear
              </button>
            )}
          </div>
        )}

        {errorMessage && <div className="job-card__error">{errorMessage}</div>}

        <div className="job-card__actions">
          <a
            className="btn btn--secondary"
            href={job.application_url}
            target="_blank"
            rel="noreferrer noopener"
          >
            View Job
          </a>
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy || job.status === 'applied'}
            onClick={() => changeStatus('applied')}
          >
            {job.status === 'applied' ? 'Applied' : 'Mark Applied'}
          </button>
        </div>
      </div>
    </article>
  )
}
