import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { keepPreviousData, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from 'next-themes'
import { RouterProvider } from 'react-router'

import { TooltipProvider } from '@/components/ui/tooltip'
import { router } from '@/routes'

import './index.css'

// The no-interruption contract: background refetches keep showing previous
// data, never re-mount the page, and stop when the tab is hidden so a
// backgrounded phone doesn't keep polling the Pi.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      placeholderData: keepPreviousData,
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      refetchIntervalInBackground: false,
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={300}>
          <RouterProvider router={router} />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
