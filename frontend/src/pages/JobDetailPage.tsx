import { useState } from 'react'
import { AsyncSection } from '../components/AsyncSection'
import { ResumeWorkspace } from '../components/ResumeWorkspace'
import { getJob, updateApplication } from '../api'
import { useAsync } from '../hooks/useAsync'
import { statusLabel, visaLabel } from '../format'
import { APPLICATION_STATUSES, type ApplicationStatus } from '../types'

interface Props {
  jobId: string
  onBack: () => void
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

export function JobDetailPage({ jobId, onBack }: Props) {
  const { data: job, loading, error, reload } = useAsync(() => getJob(jobId), [jobId])
  const [busy, setBusy] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)

  async function changeStatus(status: ApplicationStatus) {
    setBusy(true)
    setStatusError(null)
    try {
      await updateApplication(jobId, { status })
      reload()
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Update failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <button type="button" className="btn btn--ghost btn--small job-detail__back" onClick={onBack}>
        ← Back
      </button>

      <AsyncSection loading={loading} error={error}>
        {job && (
          <>
            <header className="job-detail__header">
              <div>
                <h1 className="page__title">{job.title}</h1>
                <div className="job-detail__subtitle">
                  {job.company} · {job.location || 'Location unknown'} · {job.source ?? 'unknown source'}
                </div>
                <div className="job-detail__subtitle">Visa: {visaLabel(job.visa_signal)}</div>
              </div>
              <div className="job-detail__score" aria-label="Match score">
                {job.total_score ?? '—'}
              </div>
            </header>

            <section className="page-section">
              <h2>Match Breakdown</h2>
              <div className="job-card__breakdown job-detail__breakdown">
                <ScoreRow label="Title" value={job.title_score} max={35} />
                <ScoreRow label="Skills" value={job.skills_score} max={30} />
                <ScoreRow label="Location" value={job.location_score} max={15} />
                <ScoreRow label="Seniority" value={job.seniority_score} max={10} />
                <ScoreRow label="Product" value={job.product_score} max={10} />
              </div>

              {job.matched_skills.length > 0 && (
                <>
                  <p className="page-section__hint">Matched skills</p>
                  <div className="job-card__skills">
                    {job.matched_skills.map((skill) => (
                      <span className="skill-tag skill-tag--accent" key={skill}>
                        {skill}
                      </span>
                    ))}
                  </div>
                </>
              )}
              {job.unmatched_skills.length > 0 && (
                <>
                  <p className="page-section__hint">Not matched</p>
                  <div className="job-card__skills">
                    {job.unmatched_skills.map((skill) => (
                      <span className="skill-tag skill-tag--muted" key={skill}>
                        {skill}
                      </span>
                    ))}
                  </div>
                </>
              )}
            </section>

            <section className="page-section">
              <h2>Status</h2>
              <div className="job-card__status-row">
                <label htmlFor="job-detail-status">Application status</label>
                <select
                  id="job-detail-status"
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
              {statusError && <div className="job-card__error">{statusError}</div>}
              <div className="job-detail__actions">
                <a className="btn btn--secondary" href={job.application_url} target="_blank" rel="noreferrer noopener">
                  View Original Job
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
            </section>

            <section className="page-section">
              <h2>Job Description</h2>
              <pre className="job-detail__description">{job.description}</pre>
            </section>

            <section className="page-section">
              <h2>Tailored Resume</h2>
              <ResumeWorkspace jobId={jobId} />
            </section>
          </>
        )}
      </AsyncSection>
    </div>
  )
}
