// Monsoon correlation — NWS alerts, Sonnet digest, APRS/gauge/voice rollups
// (dashboard/tabs/monsoon.py).

import { useMemo } from 'react'
import { CircleCheck, Siren, TriangleAlert } from 'lucide-react'

import { useAprs, useEvents, useGauges, useMonsoonDigest, useWeatherAlerts } from '@/api/queries'
import type { WeatherAlert } from '@/api/types'
import { SeverityChip, TypeChip } from '@/components/chips'
import { ErrorState } from '@/components/ErrorState'
import { ListSkeleton } from '@/components/ListSkeleton'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { fmtAzFull } from '@/lib/time'
import { cn } from '@/lib/utils'

function isUrgent(alert: WeatherAlert): boolean {
  const event = (alert.event ?? '').toLowerCase()
  return event.includes('flood') || alert.severity === 'Extreme' || alert.severity === 'Severe'
}

function NwsBanners() {
  const alerts = useWeatherAlerts()
  if (!alerts.data || alerts.data.count === 0) return null
  return (
    <div className="space-y-2">
      {alerts.data.results.map((alert) => {
        const urgent = isUrgent(alert)
        return (
          <div
            key={alert.id}
            className={cn(
              'flex items-start gap-2 rounded-lg border p-3 text-sm',
              urgent
                ? 'border-destructive/40 bg-destructive/10'
                : 'border-amber-400/50 bg-amber-400/10',
            )}
          >
            {urgent ? (
              <Siren className="mt-0.5 size-4 shrink-0 text-destructive" />
            ) : (
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
            )}
            <p>
              <b>{alert.event}</b> — {alert.headline || alert.area_desc || ''}
            </p>
          </div>
        )
      })}
    </div>
  )
}

function DigestCard() {
  const digest = useMonsoonDigest()
  if (digest.isPending) return <ListSkeleton rows={1} />
  if (digest.isError) return <ErrorState error={digest.error} />
  const data = digest.data
  if (!data.available) {
    return (
      <p className="text-sm text-muted-foreground">
        No monsoon digest has run yet. The agent worker runs one every 15 minutes by default.
      </p>
    )
  }
  return (
    <div className="space-y-2 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        {data.should_alert ? (
          <Badge variant="destructive" className="gap-1">
            <Siren className="size-3" /> Alert active
          </Badge>
        ) : (
          <Badge className="gap-1 bg-emerald-600 text-white">
            <CircleCheck className="size-3" /> No alert
          </Badge>
        )}
        <span className="text-xs text-muted-foreground">
          Last digest: {fmtAzFull(data.timestamp)}
        </span>
      </div>
      {data.summary && (
        <p className="text-sm">
          <b>Summary</b> — {data.summary}
        </p>
      )}
      {data.correlation_note && (
        <p className="text-sm">
          <b>Correlation note</b> — {data.correlation_note}
        </p>
      )}
      {data.correlated_event_ids.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Correlated event ids: {data.correlated_event_ids.join(', ')}
        </p>
      )}
    </div>
  )
}

interface AprsStationRollup {
  callsign: string
  temp_f: number | null
  rainfall_in: number | null
  wind_mph: number | null
  last_seen: string | null
}

function AprsRollup() {
  const aprs = useAprs({ minutes: 30, limit: 200 })

  const rollup = useMemo(() => {
    const rows = aprs.data?.results ?? []
    const weather = rows.filter(
      (r) => r.temp_f != null || r.rainfall_in != null || r.wind_mph != null,
    )
    const byCallsign = new Map<string, AprsStationRollup>()
    for (const row of weather) {
      const key = row.callsign ?? '?'
      const entry: AprsStationRollup = byCallsign.get(key) ?? {
        callsign: key,
        temp_f: null,
        rainfall_in: null,
        wind_mph: null,
        last_seen: null,
      }
      entry.temp_f = row.temp_f != null ? Math.max(entry.temp_f ?? -Infinity, row.temp_f) : entry.temp_f
      entry.rainfall_in =
        row.rainfall_in != null ? Math.max(entry.rainfall_in ?? -Infinity, row.rainfall_in) : entry.rainfall_in
      entry.wind_mph =
        row.wind_mph != null ? Math.max(entry.wind_mph ?? -Infinity, row.wind_mph) : entry.wind_mph
      if (row.timestamp && (!entry.last_seen || row.timestamp > entry.last_seen)) {
        entry.last_seen = row.timestamp
      }
      byCallsign.set(key, entry)
    }
    return [...byCallsign.values()].sort(
      (a, b) => (b.rainfall_in ?? -Infinity) - (a.rainfall_in ?? -Infinity),
    )
  }, [aprs.data])

  if (aprs.isError) return <ErrorState error={aprs.error} />
  if ((aprs.data?.count ?? 0) === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No APRS packets in the last 30 minutes. Start the APRS-IS client on the Pi.
      </p>
    )
  }
  if (rollup.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        APRS traffic is present but no weather-field reports in window.
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Callsign</TableHead>
          <TableHead className="text-right">Temp (°F)</TableHead>
          <TableHead className="text-right">Rain (in)</TableHead>
          <TableHead className="text-right">Wind (mph)</TableHead>
          <TableHead>Last seen</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rollup.map((row) => (
          <TableRow key={row.callsign}>
            <TableCell className="font-mono text-xs">{row.callsign}</TableCell>
            <TableCell className="text-right tabular-nums">{row.temp_f?.toFixed(1) ?? '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{row.rainfall_in?.toFixed(2) ?? '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{row.wind_mph?.toFixed(1) ?? '—'}</TableCell>
            <TableCell className="text-xs">{fmtAzFull(row.last_seen)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function GaugeTable() {
  const gauges = useGauges({ minutes: 60, limit: 200 })
  if (gauges.isError) return <ErrorState error={gauges.error} />
  const rows = [...(gauges.data?.results ?? [])].sort(
    (a, b) => (b.discharge_cfs ?? -Infinity) - (a.discharge_cfs ?? -Infinity),
  )
  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No gauge readings yet. Start the gauge feed on the Pi (USGS is on by default).
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Site</TableHead>
          <TableHead>Wash</TableHead>
          <TableHead>Source</TableHead>
          <TableHead className="text-right">Discharge (cfs)</TableHead>
          <TableHead className="text-right">Height (ft)</TableHead>
          <TableHead className="text-right">Precip (in)</TableHead>
          <TableHead>Time</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id}>
            <TableCell>{row.site_name ?? row.site_id}</TableCell>
            <TableCell>{row.wash ?? '—'}</TableCell>
            <TableCell>{row.source}</TableCell>
            <TableCell className="text-right tabular-nums">{row.discharge_cfs?.toFixed(1) ?? '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{row.gage_height_ft?.toFixed(2) ?? '—'}</TableCell>
            <TableCell className="text-right tabular-nums">{row.precip_in?.toFixed(2) ?? '—'}</TableCell>
            <TableCell className="text-xs">{fmtAzFull(row.timestamp)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function RelevantRadio() {
  const events = useEvents({ since_minutes: 60, limit: 200 })
  if (events.isError) return <ErrorState error={events.error} />
  const relevant = (events.data?.results ?? []).filter((r) =>
    ['fire', 'ems', 'flood_control'].includes(r.transmission_type ?? ''),
  )
  if (relevant.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No fire / EMS / flood-control transmissions in the last hour.
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>ID</TableHead>
          <TableHead>Time</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead>Locations</TableHead>
          <TableHead>Wash</TableHead>
          <TableHead>Text</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {relevant.map((row) => (
          <TableRow key={row.id}>
            <TableCell className="tabular-nums">#{row.id}</TableCell>
            <TableCell className="text-xs">{fmtAzFull(row.timestamp)}</TableCell>
            <TableCell>
              <TypeChip type={row.transmission_type} />
            </TableCell>
            <TableCell>
              <SeverityChip severity={row.severity} />
            </TableCell>
            <TableCell className="text-xs">{(row.locations ?? []).join(', ') || '—'}</TableCell>
            <TableCell className="text-xs">{row.wash_name ?? '—'}</TableCell>
            <TableCell className="max-w-md text-xs">
              {(row.corrected_text || row.raw_text || '').slice(0, 140)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export default function MonsoonPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Monsoon correlation</h1>
      <NwsBanners />
      <DigestCard />
      <Separator />
      <h2 className="text-sm font-semibold">APRS weather stations (last 30 min)</h2>
      <AprsRollup />
      <Separator />
      <h2 className="text-sm font-semibold">Stream &amp; rain gauges (last 60 min)</h2>
      <GaugeTable />
      <Separator />
      <h2 className="text-sm font-semibold">Fire / EMS / flood-control radio (last 60 min)</h2>
      <RelevantRadio />
    </div>
  )
}
