// Port of the color maps in dashboard/style.py. Unlike Folium, Leaflet divIcons
// can use these hex values directly on the map.

export const TYPE_COLORS: Record<string, string> = {
  fire: '#d9534f',
  ems: '#0275d8',
  police: '#5bc0de',
  ham: '#777777',
  weather: '#5cb85c',
  aprs: '#9b59b6',
  flood_control: '#f0ad4e',
  unknown: '#999999',
}

export const SEVERITY_COLORS: Record<string, string> = {
  high: '#d9534f',
  medium: '#f0ad4e',
  low: '#5cb85c',
  unknown: '#999999',
}

// Signal source (radio leg / feed), distinct from transmission_type: P25
// trunked, analog FM, or APRS-IS. Keyed by the `source` column value.
export const SOURCE_COLORS: Record<string, string> = {
  p25: '#2c3e50',
  analog: '#16a085',
  aprs: '#9b59b6',
}

export const SOURCE_LABELS: Record<string, string> = {
  p25: 'P25',
  analog: 'Analog FM',
  aprs: 'APRS',
}

export function typeColor(t: string | null | undefined): string {
  return TYPE_COLORS[t ?? 'unknown'] ?? TYPE_COLORS.unknown
}

export function severityColor(s: string | null | undefined): string {
  return SEVERITY_COLORS[s ?? 'unknown'] ?? SEVERITY_COLORS.unknown
}

export function sourceColor(source: string | null | undefined): string {
  return SOURCE_COLORS[source ?? ''] ?? '#777777'
}

export function sourceLabel(source: string | null | undefined): string {
  if (!source) return ''
  return SOURCE_LABELS[source] ?? source.toUpperCase()
}
