import { NavLink, Outlet } from 'react-router'

import { StatusBar } from '@/components/StatusBar'
import { Toaster } from '@/components/ui/sonner'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/', label: 'Threads' },
  { to: '/hourly', label: 'Last hour' },
  { to: '/feed', label: 'Raw feed' },
  { to: '/map', label: 'Map' },
  { to: '/activity', label: '24h activity' },
  { to: '/monsoon', label: 'Monsoon' },
  { to: '/ask', label: 'Ask' },
]

export default function App() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <h1 className="text-base font-semibold tracking-tight">
            <span aria-hidden>🌩️</span> Monsoon Ears
          </h1>
          <nav className="-mx-1 flex flex-1 items-center gap-1 overflow-x-auto px-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  cn(
                    'whitespace-nowrap rounded-full px-3 py-1.5 text-sm transition-colors',
                    isActive
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <StatusBar />
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <Toaster position="bottom-right" />
    </div>
  )
}
