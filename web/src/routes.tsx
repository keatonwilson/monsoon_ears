/* eslint-disable react-refresh/only-export-components -- route table, not a component module */
// NOTE: client route paths must not collide with API paths (the API wins on a
// hard refresh) — that's why Threads lives at "/" instead of "/threads".
import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate } from 'react-router'

import App from '@/App'
import { ListSkeleton } from '@/components/ListSkeleton'
import AskPage from '@/pages/AskPage'
import FeedPage from '@/pages/FeedPage'
import HourlyPage from '@/pages/HourlyPage'
import MonsoonPage from '@/pages/MonsoonPage'
import ThreadsPage from '@/pages/ThreadsPage'

// Leaflet and Recharts are heavy; split them out of the initial bundle.
const MapPage = lazy(() => import('@/pages/MapPage'))
const ActivityPage = lazy(() => import('@/pages/ActivityPage'))

function lazyPage(page: React.ReactNode) {
  return <Suspense fallback={<ListSkeleton rows={3} />}>{page}</Suspense>
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <ThreadsPage /> },
      { path: 'hourly', element: <HourlyPage /> },
      { path: 'feed', element: <FeedPage /> },
      { path: 'map', element: lazyPage(<MapPage />) },
      { path: 'activity', element: lazyPage(<ActivityPage />) },
      { path: 'monsoon', element: <MonsoonPage /> },
      { path: 'ask', element: <AskPage /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
