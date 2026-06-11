// One TanStack Query hook per endpoint. Polling intervals follow the plan:
// fast-moving radio data every 30s, telemetry every 60s, agent output every
// 5min — all silent background refetches (placeholderData keeps the old page).

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { FeatureCollection } from 'geojson'

import { api, apiPost, qs } from '@/api/client'
import type {
  AlertRow,
  AprsRow,
  EventRow,
  GaugeRow,
  HealthResponse,
  HourlySummary,
  HourlySummaryEnvelope,
  ListResponse,
  MonsoonDigest,
  QueryResult,
  SdrStatus,
  ThreadDetail,
  ThreadRow,
  WeatherAlert,
} from '@/api/types'

const MINUTE = 60_000

// Type aliases (not interfaces) so they satisfy qs()'s indexed param type.
export type EventsParams = {
  limit?: number
  source?: string | null
  type?: string | null
  since_minutes?: number
}

export function useEvents(params: EventsParams = {}) {
  return useQuery({
    queryKey: ['events', params],
    queryFn: () => api<ListResponse<EventRow>>(`/events${qs(params)}`),
    refetchInterval: 30_000,
  })
}

export type ThreadsParams = {
  limit?: number
  since_minutes?: number
}

export function useThreads(params: ThreadsParams = {}) {
  return useQuery({
    queryKey: ['threads', params],
    queryFn: () => api<ListResponse<ThreadRow>>(`/threads${qs(params)}`),
    refetchInterval: 30_000,
  })
}

/** Thread with its events — fetched lazily when a card is expanded. */
export function useThread(threadId: number, enabled: boolean) {
  return useQuery({
    queryKey: ['thread', threadId],
    queryFn: () => api<ThreadDetail>(`/threads/${threadId}`),
    enabled,
    staleTime: MINUTE,
  })
}

export function useResummarizeThread() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (threadId: number) => apiPost<ThreadDetail>(`/threads/${threadId}/summarize`, {}),
    onSuccess: (detail) => {
      queryClient.setQueryData(['thread', detail.id], detail)
      void queryClient.invalidateQueries({ queryKey: ['threads'] })
    },
  })
}

export function useHourlySummary() {
  return useQuery({
    queryKey: ['hourly-summary'],
    queryFn: () => api<HourlySummaryEnvelope>('/hourly-summary'),
    refetchInterval: 5 * MINUTE,
    staleTime: 4 * MINUTE,
  })
}

export function useHourlySummaries(limit = 24) {
  return useQuery({
    queryKey: ['hourly-summaries', limit],
    queryFn: () => api<ListResponse<HourlySummary>>(`/hourly-summaries${qs({ limit })}`),
    refetchInterval: 5 * MINUTE,
    staleTime: 4 * MINUTE,
  })
}

export function useAprs(params: { minutes?: number; limit?: number } = {}) {
  return useQuery({
    queryKey: ['aprs', params],
    queryFn: () => api<ListResponse<AprsRow>>(`/aprs${qs(params)}`),
    refetchInterval: MINUTE,
    staleTime: 30_000,
  })
}

export function useGauges(params: { minutes?: number; limit?: number } = {}) {
  return useQuery({
    queryKey: ['gauges', params],
    queryFn: () => api<ListResponse<GaugeRow>>(`/gauges${qs(params)}`),
    refetchInterval: MINUTE,
    staleTime: 30_000,
  })
}

export function useWeatherAlerts() {
  return useQuery({
    queryKey: ['weather-alerts'],
    queryFn: () => api<ListResponse<WeatherAlert>>('/weather/alerts'),
    refetchInterval: 5 * MINUTE,
    staleTime: 4 * MINUTE,
  })
}

export function useAlerts(params: { limit?: number; since_minutes?: number; source?: string } = {}) {
  return useQuery({
    queryKey: ['alerts', params],
    queryFn: () => api<ListResponse<AlertRow>>(`/alerts${qs(params)}`),
    refetchInterval: 5 * MINUTE,
    staleTime: 4 * MINUTE,
  })
}

export function useMonsoonDigest() {
  return useQuery({
    queryKey: ['summary'],
    queryFn: () => api<MonsoonDigest>('/summary'),
    refetchInterval: 5 * MINUTE,
    staleTime: 4 * MINUTE,
  })
}

export function useSdrStatus() {
  return useQuery({
    queryKey: ['sdr-status'],
    queryFn: () => api<SdrStatus>('/sdr/status'),
    refetchInterval: 15_000,
    staleTime: 10_000,
  })
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api<HealthResponse>('/health'),
    refetchInterval: MINUTE,
  })
}

/** Pima County wash GeoJSON — static per deployment, fetch once and keep. */
export function useWashes() {
  return useQuery({
    queryKey: ['washes'],
    queryFn: () => api<FeatureCollection>('/washes'),
    staleTime: Infinity,
    gcTime: Infinity,
  })
}

export function useNlQuery() {
  return useMutation({
    mutationFn: (question: string) => apiPost<QueryResult>('/query', { question }),
  })
}
