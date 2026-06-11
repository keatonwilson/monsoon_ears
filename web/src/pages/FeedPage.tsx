// Raw feed — recent transmissions list (dashboard/tabs/live_feed.py).

import { useMemo, useState } from 'react'
import { ChevronDown } from 'lucide-react'

import { useEvents } from '@/api/queries'
import type { EventRow } from '@/api/types'
import { SeverityChip, TypeChip } from '@/components/chips'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { ListSkeleton } from '@/components/ListSkeleton'
import { NewItemsPill } from '@/components/NewItemsPill'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { channelLabel, isNoiseEvent } from '@/lib/labels'
import { fmtAz } from '@/lib/time'
import { useDeferredList } from '@/lib/useDeferredList'
import { useBoolParam, useNumberParam, useStringParam } from '@/lib/urlState'
import { cn } from '@/lib/utils'

const TYPE_OPTIONS = ['all', 'fire', 'ems', 'police', 'weather', 'ham', 'flood_control']

function EventDetails({ event }: { event: EventRow }) {
  const entries: [string, string][] = []
  if (event.corrected_text && event.raw_text) entries.push(['raw_text', event.raw_text])
  if (event.locations?.length) entries.push(['locations', event.locations.join(', ')])
  if (event.units?.length) entries.push(['units', event.units.join(', ')])
  if (event.callsigns?.length) entries.push(['callsigns', event.callsigns.join(', ')])
  if (event.status_codes?.length) entries.push(['status_codes', event.status_codes.join(', ')])
  if (event.incident_type) entries.push(['incident_type', event.incident_type])
  if (event.wash_name) entries.push(['wash_name', event.wash_name])
  if (event.road_closure) entries.push(['road_closure', 'yes'])
  if (event.lat != null && event.lon != null) {
    entries.push(['lat / lon', `${event.lat.toFixed(5)}, ${event.lon.toFixed(5)}`])
  }
  if (entries.length === 0) {
    return <p className="py-2 text-xs text-muted-foreground">No extracted details.</p>
  }
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 py-2 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="font-medium text-muted-foreground">{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function FeedRow({
  event,
  expanded,
  onToggle,
}: {
  event: EventRow
  expanded: boolean
  onToggle: (open: boolean) => void
}) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-sm font-semibold">#{event.id}</span>
        <span className="font-mono text-xs text-muted-foreground">{fmtAz(event.timestamp)}</span>
        <TypeChip type={event.transmission_type} />
        <SeverityChip severity={event.severity} />
        <span className="ml-auto text-xs text-muted-foreground">
          {channelLabel(event)} · {(event.duration_sec ?? 0).toFixed(1)}s
        </span>
      </div>
      <p className="mt-1 text-sm">{event.corrected_text || event.raw_text}</p>
      <Collapsible open={expanded} onOpenChange={onToggle}>
        <CollapsibleTrigger className="mt-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ChevronDown className={cn('size-3.5 transition-transform', expanded && 'rotate-180')} />
          Details
        </CollapsibleTrigger>
        <CollapsibleContent>
          <EventDetails event={event} />
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

export default function FeedPage() {
  const [limit, setLimit] = useNumberParam('limit', 50)
  const [typeFilter, setTypeFilter] = useStringParam('type', 'all')
  const [showNoise, setShowNoise] = useBoolParam('noise', false)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  const params = { limit, type: typeFilter === 'all' ? null : typeFilter }
  const events = useEvents(params)

  const filtered = useMemo(() => {
    const results = events.data?.results
    if (!results) return undefined
    return showNoise ? results : results.filter((row) => !isNoiseEvent(row))
  }, [events.data, showNoise])

  const { rows, pendingCount, showPending } = useDeferredList(
    filtered,
    JSON.stringify({ ...params, showNoise }),
    expandedIds.size > 0,
  )

  const toggleExpanded = (id: number, open: boolean) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (open) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const hidden = (events.data?.count ?? 0) - (filtered?.length ?? 0)

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Recent transmissions</h1>

      <div className="flex flex-wrap items-end gap-6">
        <div className="w-48 space-y-2">
          <Label className="text-xs">Show: {limit}</Label>
          <Slider min={10} max={200} step={10} value={[limit]} onValueChange={([v]) => setLimit(v)} />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Type</Label>
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="h-8 w-40" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TYPE_OPTIONS.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2 pb-1">
          <Switch id="feed-noise" checked={showNoise} onCheckedChange={setShowNoise} />
          <Label htmlFor="feed-noise" className="text-xs">
            Show noise
          </Label>
        </div>
      </div>

      {events.isPending && <ListSkeleton />}
      {events.isError && <ErrorState error={events.error} />}

      {rows && (
        <>
          {hidden > 0 && (
            <p className="text-xs text-muted-foreground">
              {hidden} low-confidence/unknown event{hidden === 1 ? '' : 's'} hidden — toggle “Show
              noise” to see {hidden === 1 ? 'it' : 'them'}.
            </p>
          )}
          {events.data?.count === 0 && (
            <EmptyState>No events yet. The scanner + agent worker need to run for a bit.</EmptyState>
          )}
          <div className="space-y-2">
            {rows.map((event) => (
              <FeedRow
                key={event.id}
                event={event}
                expanded={expandedIds.has(event.id)}
                onToggle={(open) => toggleExpanded(event.id, open)}
              />
            ))}
          </div>
        </>
      )}

      <NewItemsPill count={pendingCount} noun="event" onClick={showPending} />
    </div>
  )
}
