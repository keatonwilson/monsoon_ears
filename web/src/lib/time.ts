// Port of dashboard/style.py time helpers. API timestamps are UTC-naive ISO
// strings; Arizona doesn't observe DST, so America/Phoenix is a fixed UTC-7.

export const AZ_TZ = 'America/Phoenix'

/** Parse an ISO timestamp (assumed UTC if no offset) into a Date. */
export function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso)
  const date = new Date(hasOffset ? iso : `${iso}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

const timeFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: AZ_TZ,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

const fullFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: AZ_TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

const dayFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: AZ_TZ,
  weekday: 'short',
  month: 'short',
  day: '2-digit',
})

const dayYearFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: AZ_TZ,
  weekday: 'short',
  month: 'short',
  day: '2-digit',
  year: 'numeric',
})

/** 'HH:MM:SS MST' — port of fmt_az(). */
export function fmtAz(iso: string | null | undefined): string {
  const date = parseUtc(iso)
  return date ? `${timeFmt.format(date)} MST` : '—'
}

/** 'YYYY-MM-DD HH:MM MST' — port of fmt_az_full(). */
export function fmtAzFull(iso: string | null | undefined): string {
  const date = parseUtc(iso)
  if (!date) return '—'
  // en-CA gives 'YYYY-MM-DD, HH:MM'; normalize the separator
  return `${fullFmt.format(date).replace(',', '')} MST`
}

/** Calendar date in AZ as 'YYYY-MM-DD', for grouping rows by day. */
export function azDateKey(iso: string | null | undefined): string {
  const date = parseUtc(iso)
  if (!date) return 'unknown'
  return fullFmt.format(date).slice(0, 10)
}

/** Group-by-date label: 'Today — Mon, May 28', 'Yesterday — …', or full date. */
export function azDateLabel(iso: string | null | undefined): string {
  const date = parseUtc(iso)
  if (!date) return 'Unknown date'
  const key = azDateKey(iso)
  const now = new Date()
  const todayKey = fullFmt.format(now).slice(0, 10)
  const yesterdayKey = fullFmt.format(new Date(now.getTime() - 86_400_000)).slice(0, 10)
  if (key === todayKey) return `Today — ${dayFmt.format(date)}`
  if (key === yesterdayKey) return `Yesterday — ${dayFmt.format(date)}`
  return dayYearFmt.format(date)
}
