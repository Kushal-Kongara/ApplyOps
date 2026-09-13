import { AsyncSection } from '../components/AsyncSection'
import { JobCardView } from '../components/JobCardView'
import { StatCard } from '../components/StatCard'
import { getDashboard } from '../api'
import { useAsync } from '../hooks/useAsync'
import type { JobCard } from '../types'

function JobGrid({ jobs, onChanged, emptyMessage }: { jobs: JobCard[]; onChanged: () => void; emptyMessage: string }) {
  if (jobs.length === 0) {
    return <div className="state state-empty">{emptyMessage}</div>
  }
  return (
    <div className="job-grid">
      {jobs.map((job) => (
        <JobCardView key={job.job_unique_key} job={job} onChanged={onChanged} />
      ))}
    </div>
  )
}

export function TodayPage() {
  const { data, loading, error, reload } = useAsync(getDashboard)

  return (
    <div className="page">
      <h1 className="page__title">Today</h1>

      <AsyncSection loading={loading} error={error}>
        {data && (
          <>
            <div className="stat-row">
              <StatCard label="High Priority" value={data.summary.high_priority} tone="accent" />
              <StatCard label="Review" value={data.summary.review} />
              <StatCard label="Follow-ups Due" value={data.summary.follow_ups_due} tone="warn" />
              <StatCard label="Applications" value={data.summary.applications_total} />
            </div>

            <section className="page-section">
              <h2>High Priority</h2>
              <p className="page-section__hint">Actively matched jobs scoring 70+.</p>
              <JobGrid jobs={data.high_priority} onChanged={reload} emptyMessage="No high-priority jobs right now." />
            </section>

            <section className="page-section">
              <h2>Review Candidates</h2>
              <p className="page-section__hint">Worth a look — scoring 65-69.</p>
              <JobGrid jobs={data.review_candidates} onChanged={reload} emptyMessage="No review candidates right now." />
            </section>

            <section className="page-section">
              <h2>Follow-ups Due</h2>
              <p className="page-section__hint">Tracked applications whose reminder date has arrived.</p>
              <JobGrid jobs={data.follow_ups} onChanged={reload} emptyMessage="No follow-ups due today." />
            </section>
          </>
        )}
      </AsyncSection>
    </div>
  )
}
