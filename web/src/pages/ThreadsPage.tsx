// Threads — clustered conversations with Haiku summaries (dashboard/tabs/threads.py).

import { useMemo, useState } from 'react'
import { ChevronDown, MapPin, RefreshCw, Truck } from 'lucide-react'
import { toast } from 'sonner'

import { useResummarizeThread, useThread, useThreads } from '@/api/queries'
import type { ThreadRow } from '@/api/types'
import { SeverityChip, SourceChip, TypeChip } from '@/components/chips'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { ListSkeleton } from '@/components/ListSkeleton'
import { NewItemsPill } from '@/components/NewItemsPill'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { channelLabel } from '@/lib/labels'
import { azDateLabel, fmtAz, fmtAzFull } from '@/lib/time'
import { useDeferredList } from '@/lib/useDeferredList'
import { useBoolParam, useNumberParam } from '@/lib/urlState'
import { cn } from '@/lib/utils'

function ThreadFragments({ threadId, open }: { threadId: number; open: boolean }) {
  const detail = useThread(threadId, open)
  if (detail.isPending) {
    return <p className="px-1 py-2 text-sm text-muted-foreground">Loading fragments…</p>
  }
  if (detail.isError) return <ErrorState error={detail.error} />
  return (
    <ul className="space-y-1.5 py-2">
      {detail.data.events.map((ev) => (
        <li key={ev.id} className="text-sm">
          <span className="font-mono text-xs text-muted-foreground">{fmtAz(ev.timestamp)}</span>{' '}
          <span className="text-xs text-muted-foreground">
            [{channelLabel(ev)}] ({(ev.duration_sec ?? 0).toFixed(1)}s)
          </span>{' '}
          — {ev.corrected_text || ev.raw_text}
        </li>
      ))}
    </ul>
  )
}

function ThreadCard({
  thread,
  expanded,
  onToggle,
}: {
  thread: ThreadRow
  expanded: boolean
  onToggle: (open: boolean) => void
}) {
  const resummarize = useResummarizeThread()

  const handleResummarize = () => {
    resummarize.mutate(thread.id, {
      onSuccess: () => toast.success(`Thread #${thread.id} re-summarized`),
      onError: (error) => toast.error(`Summarize failed: ${error.message}`),
    })
  }

  return (
    <div className="space-y-2 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-1.5 text-sm">
        <SourceChip source={thread.source} />
        <TypeChip type={thread.transmission_type} />
        <SeverityChip severity={thread.severity} />
        <span className="font-semibold">{thread.incident_type || '—'}</span>
        <span className="text-muted-foreground">
          · {channelLabel(thread)} · {thread.event_count} event{thread.event_count === 1 ? '' : 's'} ·{' '}
          {fmtAz(thread.start_timestamp)}–{fmtAz(thread.end_timestamp)}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{fmtAzFull(thread.start_timestamp)}</p>

      {thread.summary ? (
        <p className="text-sm">💬 {thread.summary}</p>
      ) : (
        <p className="text-sm italic text-muted-foreground">
          {thread.closed
            ? 'Closed thread — summary pending on next worker cycle.'
            : 'Live thread — summary will be generated once it goes idle.'}
        </p>
      )}

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
        {thread.locations.length > 0 && (
          <span className="flex items-center gap-1">
            <MapPin className="size-3" /> {thread.locations.join(', ')}
          </span>
        )}
        {thread.units.length > 0 && (
          <span className="flex items-center gap-1">
            <Truck className="size-3" /> {thread.units.join(', ')}
          </span>
        )}
        {thread.summarized_at && <span>Summarized {fmtAzFull(thread.summarized_at)}</span>}
      </div>

      <div className="flex items-center gap-2 pt-1">
        <Button
          variant="outline"
          size="sm"
          onClick={handleResummarize}
          disabled={resummarize.isPending}
          title="Force the summary agent to re-read this thread now."
        >
          <RefreshCw className={cn('size-3.5', resummarize.isPending && 'animate-spin')} />
          {resummarize.isPending ? 'Asking Haiku…' : 'Re-summarize'}
        </Button>
      </div>

      <Collapsible open={expanded} onOpenChange={onToggle}>
        <CollapsibleTrigger className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ChevronDown className={cn('size-4 transition-transform', expanded && 'rotate-180')} />
          Raw fragments ({thread.event_count})
        </CollapsibleTrigger>
        <CollapsibleContent>
          <ThreadFragments threadId={thread.id} open={expanded} />
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

export default function ThreadsPage() {
  const [windowMin, setWindowMin] = useNumberParam('window', 24 * 60)
  const [showNoise, setShowNoise] = useBoolParam('noise', false)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  const params = { since_minutes: windowMin, limit: 100 }
  const threads = useThreads(params)

  const filtered = useMemo(() => {
    const results = threads.data?.results
    if (!results) return undefined
    return showNoise ? results : results.filter((t) => !t.is_noise)
  }, [threads.data, showNoise])

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

  const hidden = (threads.data?.count ?? 0) - (filtered?.length ?? 0)

  const dayGroups = useMemo(() => {
    if (!rows) return undefined
    const groups: { label: string; threads: ThreadRow[] }[] = []
    for (const thread of rows) {
      const label = azDateLabel(thread.start_timestamp)
      const last = groups[groups.length - 1]
      if (last && last.label === label) last.threads.push(thread)
      else groups.push({ label, threads: [thread] })
    }
    return groups
  }, [rows])

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Recent conversations</h1>
        <p className="text-sm text-muted-foreground">
          Same-frequency transmissions within 90s of each other are stitched into a thread and
          summarized by Haiku 4.5 once the channel goes idle.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-6">
        <div className="w-64 space-y-2">
          <Label className="text-xs">
            Window: {windowMin >= 60 ? `${Math.round(windowMin / 60)}h` : `${windowMin}min`}
          </Label>
          <Slider
            min={30}
            max={24 * 60}
            step={30}
            value={[windowMin]}
            onValueChange={([v]) => setWindowMin(v)}
          />
        </div>
        <div className="flex items-center gap-2 pb-1">
          <Switch id="threads-noise" checked={showNoise} onCheckedChange={setShowNoise} />
          <Label htmlFor="threads-noise" className="text-xs">
            Show noise
          </Label>
        </div>
      </div>

      {threads.isPending && <ListSkeleton />}
      {threads.isError && <ErrorState error={threads.error} />}

      {rows && (
        <>
          <p className="text-xs text-muted-foreground">
            {rows.length} thread{rows.length === 1 ? '' : 's'}
            {hidden > 0 && ` · ${hidden} noise hidden`}
          </p>
          {threads.data?.count === 0 && (
            <EmptyState>No threads yet. The scanner + worker need to run for a bit.</EmptyState>
          )}
          {threads.data && threads.data.count > 0 && rows.length === 0 && (
            <EmptyState>All recent threads were noise. Toggle “Show noise” to see them.</EmptyState>
          )}
          <div className="space-y-3">
            {dayGroups?.map((group) => (
              <div key={group.label} className="space-y-3">
                <h2 className="pt-2 text-sm font-semibold">{group.label}</h2>
                {group.threads.map((thread) => (
                  <ThreadCard
                    key={thread.id}
                    thread={thread}
                    expanded={expandedIds.has(thread.id)}
                    onToggle={(open) => toggleExpanded(thread.id, open)}
                  />
                ))}
              </div>
            ))}
          </div>
        </>
      )}

      <NewItemsPill count={pendingCount} noun="thread" onClick={showPending} />
    </div>
  )
}
