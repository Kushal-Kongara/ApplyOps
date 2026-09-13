import { useMemo, useState } from 'react'
import { AsyncSection } from '../components/AsyncSection'
import { JobCardView } from '../components/JobCardView'
import { getJobs } from '../api'
import { useAsync } from '../hooks/useAsync'
import { statusLabel } from '../format'
import { APPLICATION_STATUSES, type ApplicationStatus } from '../types'

type ScoreFilter = '70' | '65' | 'all'

export function JobsPage() {
  const [search, setSearch] = useState('')
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>('all')
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | ''>('')

  const minScore = useMemo(() => (scoreFilter === 'all' ? 0 : Number(scoreFilter)), [scoreFilter])

  const { data, loading, error, reload } = useAsync(
    () => getJobs({ q: search || undefined, min_score: minScore, status: statusFilter || undefined }),
    [search, minScore, statusFilter],
  )

  return (
    <div className="page">
      <h1 className="page__title">Jobs</h1>

      <div className="filter-bar">
        <input
          type="search"
          placeholder="Search title or company…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select value={scoreFilter} onChange={(event) => setScoreFilter(event.target.value as ScoreFilter)}>
          <option value="70">Score 70+</option>
          <option value="65">Score 65+</option>
          <option value="all">All scored</option>
        </select>
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value as ApplicationStatus | '')}
        >
          <option value="">Any status</option>
          {APPLICATION_STATUSES.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </select>
      </div>

      <AsyncSection loading={loading} error={error} isEmpty={data?.length === 0} emptyMessage="No jobs match these filters.">
        <div className="job-grid">
          {data?.map((job) => (
            <JobCardView key={job.job_unique_key} job={job} onChanged={reload} />
          ))}
        </div>
      </AsyncSection>
    </div>
  )
}
