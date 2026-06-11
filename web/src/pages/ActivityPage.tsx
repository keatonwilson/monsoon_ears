// 24h activity — stacked hourly bar + channel counts (dashboard/tabs/activity.py).

import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Bot, RadioTower } from 'lucide-react'

import { useEvents, useSdrStatus } from '@/api/queries'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { ListSkeleton } from '@/components/ListSkeleton'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { channelLabel } from '@/lib/labels'
import { TYPE_COLORS, sourceLabel } from '@/lib/palette'
import { AZ_TZ, parseUtc } from '@/lib/time'

const HOUR_MS = 3_600_000

const hourFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: AZ_TZ,
  hour: '2-digit',
  hour12: false,
})

function SdrBanner() {
  const sdr = useSdrStatus()
  if (!sdr.data?.available) return null
  const leg = sdr.data.current_leg
  const label = leg === 'p25' ? 'P25 / PCWIN' : leg === 'analog' ? 'Analog scan' : (leg ?? 'idle')
  const isAgent = sdr.data.plan_source === 'agent'
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2 text-sm">
      <span className="font-medium">Current band: {label}</span>
      <Badge variant="outline" className="gap-1">
        {isAgent ? <Bot className="size-3" /> : <RadioTower className="size-3" />}
        {isAgent ? 'agent' : 'rules'}
      </Badge>
      {sdr.data.rationale && (
        <span className="text-xs italic text-muted-foreground">{sdr.data.rationale}</span>
      )}
    </div>
  )
}

export default function ActivityPage() {
  const events = useEvents({ since_minutes: 24 * 60, limit: 500 })
  const rows = events.data?.results

  const { chartData, typesPresent, channelCounts, distinctChannels, bySource } = useMemo(() => {
    if (!rows || rows.length === 0) {
      return {
        chartData: [],
        typesPresent: [] as string[],
        channelCounts: [] as { source: string; channel: string; events: number }[],
        distinctChannels: 0,
        bySource: '',
      }
    }

    // Hour buckets: AZ is a fixed UTC-7, so flooring epoch hours is correct.
    const buckets = new Map<number, Record<string, number>>()
    const types = new Set<string>()
    const channels = new Map<string, { source: string; channel: string; events: number }>()
    const sources = new Map<string, number>()

    for (const row of rows) {
      const date = parseUtc(row.timestamp)
      if (date) {
        const hour = Math.floor(date.getTime() / HOUR_MS) * HOUR_MS
        const type = row.transmission_type || 'unknown'
        types.add(type)
        const bucket = buckets.get(hour) ?? {}
        bucket[type] = (bucket[type] ?? 0) + 1
        buckets.set(hour, bucket)
      }

      const source = row.source || 'analog'
      sources.set(source, (sources.get(source) ?? 0) + 1)
      const channel = channelLabel(row)
      const channelKey = `${source}|${channel}`
      const entry = channels.get(channelKey) ?? { source, channel, events: 0 }
      entry.events += 1
      channels.set(channelKey, entry)
    }

    const data = [...buckets.entries()]
      .sort(([a], [b]) => a - b)
      .map(([hour, counts]) => ({ hour: `${hourFmt.format(new Date(hour))}:00`, ...counts }))

    return {
      chartData: data,
      typesPresent: [...types].sort(),
      channelCounts: [...channels.values()].sort((a, b) => b.events - a.events),
      distinctChannels: channels.size,
      bySource: [...sources.entries()].map(([s, n]) => `${sourceLabel(s)} ${n}`).join(' · '),
    }
  }, [rows])

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Activity in the last 24 hours</h1>
      <SdrBanner />

      {events.isPending && <ListSkeleton rows={3} />}
      {events.isError && <ErrorState error={events.error} />}

      {rows && rows.length === 0 && <EmptyState>No events in the last 24 hours yet.</EmptyState>}

      {rows && rows.length > 0 && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border p-4">
              <p className="text-2xl font-semibold tabular-nums">{rows.length}</p>
              <p className="text-xs text-muted-foreground">Events captured</p>
            </div>
            <div className="rounded-lg border p-4">
              <p className="text-2xl font-semibold tabular-nums">{distinctChannels}</p>
              <p className="text-xs text-muted-foreground">Distinct channels</p>
            </div>
            <div className="rounded-lg border p-4">
              <p className="text-2xl font-semibold">{bySource || '—'}</p>
              <p className="text-xs text-muted-foreground">By source</p>
            </div>
          </div>

          <div className="rounded-lg border p-4">
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="hour" fontSize={11} />
                <YAxis allowDecimals={false} fontSize={11} />
                <ChartTooltip />
                <Legend />
                {typesPresent.map((type) => (
                  <Bar
                    key={type}
                    dataKey={type}
                    stackId="hour"
                    fill={TYPE_COLORS[type] ?? TYPE_COLORS.unknown}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
            <p className="text-center text-xs text-muted-foreground">Hour (Arizona)</p>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Channel</TableHead>
                <TableHead className="text-right">Events</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {channelCounts.map((row) => (
                <TableRow key={`${row.source}|${row.channel}`}>
                  <TableCell>{sourceLabel(row.source)}</TableCell>
                  <TableCell>{row.channel}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.events}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  )
}
