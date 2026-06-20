// Persistent header strip replacing the Streamlit sidebar: API health dot,
// live SDR band with rationale tooltip, data freshness, and an NWS alert badge.

import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { useEffect, useState } from 'react'
import { Radio, TriangleAlert } from 'lucide-react'

import { useHealth, useSdrStatus, useWeatherAlerts } from '@/api/queries'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

function HealthDot() {
  const health = useHealth()
  const ok = health.data?.status === 'ok'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="flex items-center gap-1.5">
          <span
            className={cn(
              'size-2 rounded-full',
              ok ? 'bg-emerald-500' : 'bg-red-500 animate-pulse',
            )}
          />
          <span className="text-xs text-muted-foreground">
            {ok ? `API v${health.data?.version}` : 'API offline'}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {ok ? 'Read-only API on the Pi is reachable' : 'Cannot reach the Monsoon Ears API'}
      </TooltipContent>
    </Tooltip>
  )
}

function SdrBand() {
  const sdr = useSdrStatus()
  if (!sdr.data?.available) return null
  const leg = sdr.data.current_leg
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Radio className="size-3.5" />
          <span className="font-medium uppercase">{leg ?? 'idle'}</span>
          {sdr.data.plan_source && (
            <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
              {sdr.data.plan_source}
            </Badge>
          )}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        {sdr.data.rationale ?? 'SDR supervisor is time-sharing the dongle'}
      </TooltipContent>
    </Tooltip>
  )
}

function NwsBadge() {
  const alerts = useWeatherAlerts()
  const count = alerts.data?.count ?? 0
  if (count === 0) return null
  return (
    <Link to="/monsoon" className="flex items-center gap-1 text-xs font-medium text-amber-600">
      <TriangleAlert className="size-3.5" />
      {count} NWS alert{count === 1 ? '' : 's'}
    </Link>
  )
}

/** "updated Ns ago" across all queries — pulses subtly when data lands. */
function Freshness() {
  const queryClient = useQueryClient()
  const [label, setLabel] = useState('')

  useEffect(() => {
    const update = () => {
      const updatedAts = queryClient
        .getQueryCache()
        .getAll()
        .map((q) => q.state.dataUpdatedAt)
        .filter((t) => t > 0)
      if (updatedAts.length === 0) {
        setLabel('')
        return
      }
      const seconds = Math.max(0, Math.round((Date.now() - Math.max(...updatedAts)) / 1000))
      setLabel(seconds < 2 ? 'updated just now' : `updated ${seconds}s ago`)
    }
    update()
    const interval = setInterval(update, 1000)
    return () => clearInterval(interval)
  }, [queryClient])

  if (!label) return null
  return <span className="text-xs tabular-nums text-muted-foreground">{label}</span>
}

export function StatusBar() {
  return (
    <div className="flex items-center gap-4">
      <HealthDot />
      <SdrBand />
      <NwsBadge />
      <Freshness />
    </div>
  )
}
