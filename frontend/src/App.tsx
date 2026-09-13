import { useState } from 'react'
import { ApplicationsPage } from './pages/ApplicationsPage'
import { FollowUpsPage } from './pages/FollowUpsPage'
import { JobsPage } from './pages/JobsPage'
import { RecentPage } from './pages/RecentPage'
import { TodayPage } from './pages/TodayPage'

type PageId = 'today' | 'recent' | 'jobs' | 'applications' | 'follow-ups'

const NAV_ITEMS: { id: PageId; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'recent', label: 'Recent' },
  { id: 'jobs', label: 'Jobs' },
  { id: 'applications', label: 'Applications' },
  { id: 'follow-ups', label: 'Follow-ups' },
]

function renderPage(page: PageId) {
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
  }
}

function App() {
  const [page, setPage] = useState<PageId>('today')

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
                onClick={() => setPage(item.id)}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <main className="app-main">{renderPage(page)}</main>
    </div>
  )
}

export default App
