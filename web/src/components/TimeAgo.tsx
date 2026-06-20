import { useEffect, useState } from 'react'

import { fmtAzFull, parseUtc } from '@/lib/time'

function relativeLabel(date: Date): string {
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

/** Relative timestamp ("4m ago") with the absolute AZ time on hover. */
export function TimeAgo({ iso }: { iso: string | null | undefined }) {
  const date = parseUtc(iso)
  const [, tick] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => tick((n) => n + 1), 30_000)
    return () => clearInterval(interval)
  }, [])

  if (!date) return <span>—</span>
  return (
    <span title={fmtAzFull(iso)} className="tabular-nums">
      {relativeLabel(date)}
    </span>
  )
}
