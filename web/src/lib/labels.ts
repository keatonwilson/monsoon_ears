// Ports of channel_label() (dashboard/style.py) and the raw-feed noise
// predicate (dashboard/tabs/live_feed.py).

interface ChannelFields {
  source?: string | null
  talkgroup_id?: number | null
  talkgroup_label?: string | null
  frequency_mhz?: number | null
}

/** Human channel name: talkgroup for P25, frequency for analog. */
export function channelLabel(row: ChannelFields): string {
  if (row.source === 'p25') {
    const label = row.talkgroup_label || `TG ${row.talkgroup_id}`
    return `P25 · ${label}`
  }
  return row.frequency_mhz ? `${row.frequency_mhz.toFixed(4)} MHz` : '—'
}

export const NOISE_CONFIDENCE = 0.35

interface NoiseFields {
  transmission_type?: string | null
  confidence?: number | null
}

/** An event is noise when it's unclassified with low Whisper confidence. */
export function isNoiseEvent(row: NoiseFields): boolean {
  const type = (row.transmission_type ?? 'unknown').toLowerCase()
  if (type !== '' && type !== 'unknown') return false
  return (row.confidence ?? 0) <= NOISE_CONFIDENCE
}
