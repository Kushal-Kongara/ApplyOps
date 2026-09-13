import { AsyncSection } from '../components/AsyncSection'
import { JobCardView } from '../components/JobCardView'
import { getFollowUps } from '../api'
import { useAsync } from '../hooks/useAsync'
import type { JobCard } from '../types'

function FollowUpGrid({ jobs, onChanged, emptyMessage }: { jobs: JobCard[]; onChanged: () => void; emptyMessage: string }) {
  if (jobs.length === 0) {
    return <div className="state state-empty">{emptyMessage}</div>
  }
  return (
    <div className="job-grid">
      {jobs.map((job) => (
        <JobCardView key={job.job_unique_key} job={job} onChanged={onChanged} showFollowUpEditor />
      ))}
    </div>
  )
}

export function FollowUpsPage() {
  const { data, loading, error, reload } = useAsync(getFollowUps)

  return (
    <div className="page">
      <h1 className="page__title">Follow-ups</h1>

      <AsyncSection loading={loading} error={error}>
        {data && (
          <>
            <section className="page-section">
              <h2>Due / Overdue</h2>
              <FollowUpGrid jobs={data.due} onChanged={reload} emptyMessage="Nothing due right now." />
            </section>

            <section className="page-section">
              <h2>Upcoming</h2>
              <FollowUpGrid jobs={data.upcoming} onChanged={reload} emptyMessage="No upcoming follow-ups scheduled." />
            </section>
          </>
        )}
      </AsyncSection>
    </div>
  )
}
