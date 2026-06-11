// NOTE: client route paths must not collide with API paths (the API wins on a
// hard refresh) — that's why Threads lives at "/" instead of "/threads".
import { createBrowserRouter, Navigate } from 'react-router'

import App from '@/App'
import ActivityPage from '@/pages/ActivityPage'
import AskPage from '@/pages/AskPage'
import FeedPage from '@/pages/FeedPage'
import HourlyPage from '@/pages/HourlyPage'
import MapPage from '@/pages/MapPage'
import MonsoonPage from '@/pages/MonsoonPage'
import ThreadsPage from '@/pages/ThreadsPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <ThreadsPage /> },
      { path: 'hourly', element: <HourlyPage /> },
      { path: 'feed', element: <FeedPage /> },
      { path: 'map', element: <MapPage /> },
      { path: 'activity', element: <ActivityPage /> },
      { path: 'monsoon', element: <MonsoonPage /> },
      { path: 'ask', element: <AskPage /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
