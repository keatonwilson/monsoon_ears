// Thin fetch wrapper. URLs are relative: in production FastAPI serves the SPA
// from the same origin; in dev the Vite proxy forwards to the API.

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

async function parseDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // non-JSON error body — fall through to the status line
  }
  return `${res.status} ${res.statusText}`
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { Accept: 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    throw new ApiError(res.status, await parseDetail(res))
  }
  return (await res.json()) as T
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** Build a query string, dropping null/undefined params. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined) search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}
