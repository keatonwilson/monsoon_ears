import { Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useEffect, useRef } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'

import { StatusBar } from '@/components/StatusBar'
import { Button } from '@/components/ui/button'
import { Toaster } from '@/components/ui/sonner'
import { cn } from '@/lib/utils'

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-8"
      aria-label="Toggle dark mode"
      onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
    >
      <Sun className="size-4 dark:hidden" />
      <Moon className="hidden size-4 dark:block" />
    </Button>
  )
}

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
  const navRef = useRef<HTMLElement>(null)
  const { pathname } = useLocation()

  // Keep the active tab in view when navigating — otherwise a route whose tab
  // is scrolled off-screen leaves no visible indication of where you are.
  useEffect(() => {
    const active = navRef.current?.querySelector('[aria-current="page"]')
    active?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' })
  }, [pathname])

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto max-w-6xl px-4 pt-3">
          {/* Title + status/theme get their own row and may wrap freely — they're
              a handful of short items, not the thing that needs to scroll. */}
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <h1 className="text-base font-semibold tracking-tight">
              <span aria-hidden>🌩️</span> Monsoon Ears
            </h1>
            <div className="flex items-center gap-2">
              <StatusBar />
              <ThemeToggle />
            </div>
          </div>
        </div>
        {/* Nav gets its own full-width row below — always scrolls, never
            competes with the title/status row for space (that competition
            was the source of the old wrap-vs-scroll conflict). The mask
            fades both edges as a constant "there's more" affordance, no JS
            scroll-position tracking needed. */}
        <div className="mx-auto max-w-6xl px-2 pb-1 [mask-image:linear-gradient(to_right,transparent,black_16px,black_calc(100%-16px),transparent)]">
          <nav
            ref={navRef}
            className="flex items-center gap-1 overflow-x-auto px-2 py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  cn(
                    'shrink-0 whitespace-nowrap rounded-full px-3 py-1.5 text-sm transition-colors',
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
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <Toaster position="bottom-right" />
    </div>
  )
}
