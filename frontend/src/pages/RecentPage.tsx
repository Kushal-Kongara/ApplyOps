import { useState } from 'react'
import { AsyncSection } from '../components/AsyncSection'
import { JobCardView } from '../components/JobCardView'
import { StatCard } from '../components/StatCard'
import { getRecentJobs } from '../api'
import { useAsync } from '../hooks/useAsync'
import { useInterval } from '../hooks/useInterval'
import type { RecentBucket, RecentJobCard } from '../types'

const HIGH_PRIORITY_MIN_SCORE = 70 // display grouping only — same threshold the rest of the app already uses
const POLL_INTERVAL_MS = 60_000

function splitByPriority(jobs: RecentJobCard[]) {
  // `jobs` arrives already sorted (score desc, then freshness) by the
  // backend; this only decides which of two headings each one renders
  // under, it never re-sorts or re-filters.
  return {
    high: jobs.filter((job) => (job.total_score ?? 0) >= HIGH_PRIORITY_MIN_SCORE),
    review: jobs.filter((job) => (job.total_score ?? 0) < HIGH_PRIORITY_MIN_SCORE),
  }
}

function JobGroup({ label, jobs, onChanged }: { label: string; jobs: RecentJobCard[]; onChanged: () => void }) {
  if (jobs.length === 0) return null
  return (
    <>
      <div className="recent-group-label">{label}</div>
      <div className="job-grid">
        {jobs.map((job) => (
          <JobCardView key={job.job_unique_key} job={job} onChanged={onChanged} discoveredAt={job.first_seen_at} />
        ))}
      </div>
    </>
  )
}

function BucketSection({ bucket, onChanged }: { bucket: RecentBucket; onChanged: () => void }) {
  // Empty buckets are hidden rather than rendered as twelve mostly-blank
  // sections — chronological order among the populated ones is preserved
  // since we render straight from the backend's already-ordered list.
  if (bucket.count === 0) return null

  const { high, review } = splitByPriority(bucket.jobs)

  return (
    <section className="recent-bucket">
      <div className="recent-bucket__header">
        <h2>{bucket.label}</h2>
        <span className="recent-bucket__count">
          {bucket.count} job{bucket.count === 1 ? '' : 's'}
        </span>
      </div>
      <JobGroup label="High Priority" jobs={high} onChanged={onChanged} />
      <JobGroup label="Review" jobs={review} onChanged={onChanged} />
    </section>
  )
}

const OLDER_PAGE_SIZE = 25

export function RecentPage() {
  const [olderLimit, setOlderLimit] = useState(OLDER_PAGE_SIZE)

  const { data, loading, error, reload } = useAsync(
    () => getRecentJobs({ older_limit: olderLimit }),
    [olderLimit],
  )

  // Backend refreshes every 2 hours on its own schedule; this just
  // periodically re-reads it so newly discovered jobs show up here
  // without a manual page reload.
  useInterval(reload, POLL_INTERVAL_MS)

  return (
    <div className="page">
      <h1 className="page__title">Recent Jobs</h1>

      <AsyncSection loading={loading} error={error}>
        {data && (
          <>
            <div className="stat-row">
              <StatCard label="Last 24 Hours" value={data.summary.last_24h} />
              <StatCard label="High Priority" value={data.summary.high_priority} tone="accent" />
              <StatCard label="Review" value={data.summary.review} />
            </div>

            {data.summary.last_24h === 0 && (
              <div className="state state-empty" style={{ marginTop: 24 }}>
                No jobs discovered in the last 24 hours yet.
              </div>
            )}

            {data.buckets.map((bucket) => (
              <BucketSection key={bucket.key} bucket={bucket} onChanged={reload} />
            ))}

            {data.older.count > 0 && (
              <section className="recent-bucket">
                <div className="recent-bucket__header">
                  <h2>{data.older.label}</h2>
                  <span className="recent-bucket__count">
                    {data.older.count} job{data.older.count === 1 ? '' : 's'}
                  </span>
                </div>
                <div className="job-grid">
                  {data.older.jobs.map((job) => (
                    <JobCardView
                      key={job.job_unique_key}
                      job={job}
                      onChanged={reload}
                      discoveredAt={job.first_seen_at}
                    />
                  ))}
                </div>
                {data.older.jobs.length < data.older.count && (
                  <div className="load-more-row">
                    <button
                      type="button"
                      className="btn btn--secondary"
                      onClick={() => setOlderLimit((limit) => limit + OLDER_PAGE_SIZE)}
                    >
                      Show more ({data.older.count - data.older.jobs.length} remaining)
                    </button>
                  </div>
                )}
              </section>
            )}
          </>
        )}
      </AsyncSection>
    </div>
  )
}
