// Mirrors of the FastAPI serializers in api/routes/*.py. List endpoints wrap
// rows in {count, results}; timestamps are UTC-naive ISO strings (see lib/time.ts).

export interface ListResponse<T> {
  count: number
  results: T[]
}

export type Source = 'analog' | 'p25' | 'aprs'

export type TransmissionType =
  | 'fire'
  | 'ems'
  | 'police'
  | 'weather'
  | 'ham'
  | 'flood_control'
  | 'unknown'

export type Severity = 'high' | 'medium' | 'low' | 'unknown'

// api/routes/events.py::_serialize
export interface EventRow {
  id: number
  timestamp: string | null
  frequency_mhz: number | null
  raw_text: string | null
  corrected_text: string | null
  duration_sec: number | null
  source: Source | null
  talkgroup_id: number | null
  talkgroup_label: string | null
  transmission_type: TransmissionType | null
  confidence: number | null
  language: string | null
  locations: string[] | null
  incident_type: string | null
  callsigns: string[] | null
  units: string[] | null
  status_codes: string[] | null
  severity: Severity | null
  lat: number | null
  lon: number | null
  wash_name: string | null
  road_closure: boolean | null
}

// api/routes/threads.py::_serialize_thread (events only when include_events)
export interface ThreadEvent {
  id: number
  timestamp: string | null
  raw_text: string | null
  corrected_text: string | null
  duration_sec: number | null
  source: Source | null
  talkgroup_id: number | null
  talkgroup_label: string | null
  transmission_type: TransmissionType | null
  severity: Severity | null
}

export interface ThreadRow {
  id: number
  frequency_mhz: number | null
  source: Source | null
  talkgroup_id: number | null
  talkgroup_label: string | null
  start_timestamp: string | null
  end_timestamp: string | null
  event_count: number
  event_ids: number[]
  summary: string | null
  transmission_type: TransmissionType | null
  severity: Severity | null
  locations: string[]
  units: string[]
  incident_type: string | null
  summarized_at: string | null
  closed: boolean
  is_noise: boolean
}

export interface ThreadDetail extends ThreadRow {
  events: ThreadEvent[]
}

// api/routes/hourly.py::_serialize
export interface HourlySummary {
  id: number
  generated_at: string | null
  window_start: string | null
  window_end: string | null
  summary: string | null
  event_count: number
  by_type: Record<string, number>
  top_incidents: string[]
  severity_max: Severity | null
  gauge_note: string | null
  weather_note: string | null
}

export interface HourlySummaryEnvelope {
  summary: HourlySummary | null
}

// api/routes/aprs.py::_serialize
export interface AprsRow {
  id: number
  timestamp: string | null
  callsign: string | null
  lat: number | null
  lon: number | null
  symbol: string | null
  comment: string | null
  temp_f: number | null
  rainfall_in: number | null
  wind_mph: number | null
  source: string | null
}

// api/routes/gauges.py::_serialize
export interface GaugeRow {
  id: number
  timestamp: string | null
  source: string | null
  site_id: string | null
  site_name: string | null
  wash: string | null
  lat: number | null
  lon: number | null
  discharge_cfs: number | null
  gage_height_ft: number | null
  precip_in: number | null
}

// api/routes/weather.py::_serialize
export interface WeatherAlert {
  id: number
  alert_id: string | null
  event: string | null
  severity: string | null
  certainty: string | null
  urgency: string | null
  headline: string | null
  area_desc: string | null
  onset: string | null
  expires: string | null
  sent: string | null
}

// api/routes/alerts.py::_serialize
export interface AlertRow {
  id: number
  timestamp: string | null
  source: 'rule' | 'monsoon_digest' | null
  transcription_id: number | null
  should_alert: boolean | null
  reason: string | null
  summary: string | null
  correlation_note: string | null
  correlated_event_ids: number[]
}

// api/routes/summary.py::get_summary
export interface MonsoonDigest {
  available: boolean
  timestamp: string | null
  should_alert: boolean | null
  reason: string | null
  summary: string | null
  correlation_note: string | null
  correlated_event_ids: number[]
}

// api/routes/sdr.py — pass-through of ingestion/sdr_supervisor.py::_write_status
export interface SdrStatus {
  available: boolean
  generated_at?: string
  current_leg?: 'analog' | 'p25' | null
  current_dwell_sec?: number | null
  ends_at?: string
  plan_source?: string
  rationale?: string
  weights?: Record<string, number>
  segments?: { leg: string; seconds: number }[]
}

// api/routes/query.py::nl_query
export interface QueryResult {
  sql: string
  row_count: number
  rows: Record<string, unknown>[]
}

export interface HealthResponse {
  status: string
  version: string
}
