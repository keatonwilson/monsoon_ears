# Monsoon Ears — web dashboard

React SPA replacing the Streamlit dashboard. Served in production by the
FastAPI app (`api/main.py`) from `web/dist/` on `:8000`; same origin as the
API, so all requests use relative URLs.

## Stack

Vite · React 19 · TypeScript · Tailwind v4 · shadcn/ui · TanStack Query v5 ·
react-router v7. Charts: Recharts. Map: react-leaflet.

## Develop

```bash
cd web
npm install
npm run dev                 # proxies API paths to http://localhost:8000
MONSOON_API=http://monsoon-ears.local:8000 npm run dev   # against the live Pi
```

## Deploy

```bash
npm run build               # emits web/dist/
../scripts/sync_to_pi.sh    # rsyncs the repo (dist included) to the Pi
```

The Pi picks up static changes immediately; restart `monsoon-api` only when
Python changed.

## Conventions

- Data fetching goes through hooks in `src/api/queries.ts` — never raw fetch
  in components. Background refetches must not disturb the UI: skeletons only
  on first load, stable row keys, `placeholderData: keepPreviousData`.
- Client route paths must not collide with API paths (the API wins on hard
  refresh) — Threads lives at `/` for this reason.
- Timestamps from the API are UTC-naive; always render via `src/lib/time.ts`
  (America/Phoenix).
