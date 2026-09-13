import { useState } from 'react'
import { AsyncSection } from '../components/AsyncSection'
import { getApplications, updateApplication } from '../api'
import { useAsync } from '../hooks/useAsync'
import { formatDate, statusLabel } from '../format'
import { APPLICATION_STATUSES, type ApplicationRecord, type ApplicationStatus } from '../types'

function StatusCell({ record, onChanged }: { record: ApplicationRecord; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)

  async function changeStatus(status: ApplicationStatus) {
    setBusy(true)
    try {
      await updateApplication(record.job_unique_key, { status })
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <select value={record.status} disabled={busy} onChange={(event) => changeStatus(event.target.value as ApplicationStatus)}>
      {APPLICATION_STATUSES.map((status) => (
        <option key={status} value={status}>
          {statusLabel(status)}
        </option>
      ))}
    </select>
  )
}

export function ApplicationsPage() {
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | ''>('')

  const { data, loading, error, reload } = useAsync(
    () => getApplications(statusFilter || undefined),
    [statusFilter],
  )

  return (
    <div className="page">
      <h1 className="page__title">Applications</h1>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as ApplicationStatus | '')}>
          <option value="">Any status</option>
          {APPLICATION_STATUSES.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </select>
      </div>

      <AsyncSection
        loading={loading}
        error={error}
        isEmpty={data?.length === 0}
        emptyMessage="No tracked applications yet. Mark a job applied from the Today or Jobs page to start tracking it."
      >
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Company</th>
                <th>Status</th>
                <th>Last Action</th>
                <th>Applied</th>
                <th>Next Follow-up</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {data?.map((record) => (
                <tr key={record.job_unique_key}>
                  <td>
                    <a href={record.application_url} target="_blank" rel="noreferrer noopener">
                      {record.title}
                    </a>
                  </td>
                  <td>{record.company}</td>
                  <td>
                    <StatusCell record={record} onChanged={reload} />
                  </td>
                  <td>{formatDate(record.last_action_at)}</td>
                  <td>{formatDate(record.applied_at) ?? '—'}</td>
                  <td>{formatDate(record.next_follow_up_at) ?? '—'}</td>
                  <td className="data-table__notes">{record.notes || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AsyncSection>
    </div>
  )
}
