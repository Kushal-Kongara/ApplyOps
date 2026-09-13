import { useState } from 'react'
import { ApplicationsPage } from './pages/ApplicationsPage'
import { FollowUpsPage } from './pages/FollowUpsPage'
import { JobDetailPage } from './pages/JobDetailPage'
import { JobsPage } from './pages/JobsPage'
import { RecentPage } from './pages/RecentPage'
import { TodayPage } from './pages/TodayPage'
import { NavigationProvider } from './navigation'

type PageId = 'today' | 'recent' | 'jobs' | 'applications' | 'follow-ups' | 'job-detail'

const NAV_ITEMS: { id: PageId; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'recent', label: 'Recent' },
  { id: 'jobs', label: 'Jobs' },
  { id: 'applications', label: 'Applications' },
  { id: 'follow-ups', label: 'Follow-ups' },
]

function App() {
  const [page, setPage] = useState<PageId>('today')
  // The job-detail page is reached from a card on any other page, never
  // from the sidebar directly, so its target job lives outside `page`.
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  // Where to return to when the user leaves the job-detail page.
  const [previousPage, setPreviousPage] = useState<PageId>('today')

  function openJob(jobUniqueKey: string) {
    setPreviousPage(page)
    setSelectedJobId(jobUniqueKey)
    setPage('job-detail')
  }

  function closeJobDetail() {
    setPage(previousPage)
    setSelectedJobId(null)
  }

  function renderPage() {
    switch (page) {
      case 'today':
        return <TodayPage />
      case 'recent':
        return <RecentPage />
      case 'jobs':
        return <JobsPage />
      case 'applications':
        return <ApplicationsPage />
      case 'follow-ups':
        return <FollowUpsPage />
      case 'job-detail':
        return selectedJobId ? <JobDetailPage jobId={selectedJobId} onBack={closeJobDetail} /> : null
    }
  }

  return (
    <div className="app-shell">
      <nav className="sidebar">
        <div className="sidebar__brand">JobOS</div>
        <ul className="sidebar__nav">
          {NAV_ITEMS.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={item.id === page ? 'sidebar__link sidebar__link--active' : 'sidebar__link'}
                onClick={() => {
                  setSelectedJobId(null)
                  setPage(item.id)
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <main className="app-main">
        <NavigationProvider value={openJob}>{renderPage()}</NavigationProvider>
      </main>
    </div>
  )
}

export default App
