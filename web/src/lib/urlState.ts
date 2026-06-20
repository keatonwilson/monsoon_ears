// Filter state lives in URL search params so background refetches can't reset
// it and any view is deep-linkable from a phone on the tailnet.

import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

export function useNumberParam(key: string, fallback: number): [number, (v: number) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get(key)
  const parsed = raw === null ? NaN : Number(raw)
  const value = Number.isFinite(parsed) ? parsed : fallback

  const set = useCallback(
    (v: number) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (v === fallback) next.delete(key)
          else next.set(key, String(v))
          return next
        },
        { replace: true },
      )
    },
    [key, fallback, setParams],
  )
  return [value, set]
}

export function useBoolParam(key: string, fallback = false): [boolean, (v: boolean) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get(key)
  const value = raw === null ? fallback : raw === '1'

  const set = useCallback(
    (v: boolean) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (v === fallback) next.delete(key)
          else next.set(key, v ? '1' : '0')
          return next
        },
        { replace: true },
      )
    },
    [key, fallback, setParams],
  )
  return [value, set]
}

export function useStringParam(key: string, fallback: string): [string, (v: string) => void] {
  const [params, setParams] = useSearchParams()
  const value = params.get(key) ?? fallback

  const set = useCallback(
    (v: string) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (v === fallback) next.delete(key)
          else next.set(key, v)
          return next
        },
        { replace: true },
      )
    },
    [key, fallback, setParams],
  )
  return [value, set]
}
