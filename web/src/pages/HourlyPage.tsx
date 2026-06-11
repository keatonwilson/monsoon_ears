// Last hour — hourly rollup of every source (dashboard/tabs/hourly.py).

import { useHourlySummaries, useHourlySummary } from '@/api/queries'
import type { HourlySummary } from '@/api/types'
import { SeverityChip } from '@/components/chips'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { ListSkeleton } from '@/components/ListSkeleton'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Separator } from '@/components/ui/separator'
import { fmtAz, fmtAzFull } from '@/lib/time'

function SummaryBody({ summary }: { summary: HourlySummary }) {
  const byType = Object.entries(summary.by_type).sort(([, a], [, b]) => b - a)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <SeverityChip severity={summary.severity_max} />
        <span className="font-semibold">
          {fmtAz(summary.window_start)}–{fmtAz(summary.window_end)}
        </span>
        <span className="text-muted-foreground">
          · {summary.event_count} event{summary.event_count === 1 ? '' : 's'}
        </span>
      </div>

      {summary.summary && <p className="text-sm">💬 {summary.summary}</p>}

      {byType.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {byType.map(([type, count]) => (
            <div key={type} className="min-w-20 rounded-lg border px-3 py-2 text-center">
              <p className="text-lg font-semibold tabular-nums">{count}</p>
              <p className="text-xs text-muted-foreground">{type}</p>
            </div>
          ))}
        </div>
      )}

      {summary.top_incidents.length > 0 && (
        <div>
          <p className="text-sm font-medium">Top incidents</p>
          <ul className="list-inside list-disc text-sm text-muted-foreground">
            {summary.top_incidents.map((incident) => (
              <li key={incident}>{incident}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-x-8 gap-y-1 text-xs text-muted-foreground">
        {summary.gauge_note && <span>🌊 {summary.gauge_note}</span>}
        {summary.weather_note && <span>⛈️ {summary.weather_note}</span>}
      </div>
    </div>
  )
}

export default function HourlyPage() {
  const latest = useHourlySummary()
  const history = useHourlySummaries(24)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Last hour at a glance</h1>
        <p className="text-sm text-muted-foreground">
          A wide-angle rollup of every source — voice by type, top incidents, gauge + weather
          posture — regenerated once an hour.
        </p>
      </div>

      {latest.isPending && <ListSkeleton rows={2} />}
      {latest.isError && <ErrorState error={latest.error} />}
      {latest.data &&
        (latest.data.summary ? (
          <div className="space-y-2 rounded-lg border bg-card p-4">
            <p className="text-xs text-muted-foreground">
              Generated {fmtAzFull(latest.data.summary.generated_at)}
            </p>
            <SummaryBody summary={latest.data.summary} />
          </div>
        ) : (
          <EmptyState>No hourly summary yet — the worker generates one each hour.</EmptyState>
        ))}

      <Separator />
      <h2 className="text-sm font-semibold">Earlier hours</h2>

      {history.isError && <ErrorState error={history.error} />}
      {history.data && history.data.results.length <= 1 && (
        <p className="text-sm text-muted-foreground">No earlier rollups in the window yet.</p>
      )}
      {history.data && history.data.results.length > 1 && (
        <Accordion type="multiple" className="w-full">
          {history.data.results.slice(1).map((summary) => (
            <AccordionItem key={summary.id} value={String(summary.id)}>
              <AccordionTrigger className="text-sm">
                {fmtAz(summary.window_start)}–{fmtAz(summary.window_end)} · {summary.event_count}{' '}
                event{summary.event_count === 1 ? '' : 's'}
              </AccordionTrigger>
              <AccordionContent>
                <SummaryBody summary={summary} />
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      )}
    </div>
  )
}
