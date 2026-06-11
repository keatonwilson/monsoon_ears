import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Every API route prefix lives at the origin root (no /api namespace), so the
// dev proxy enumerates them. Production is same-origin (FastAPI serves dist/)
// and needs no proxy. Point MONSOON_API at the Pi to develop against live data.
const API_PATHS = [
  'events',
  'threads',
  'aprs',
  'gauges',
  'weather',
  'alerts',
  'summary',
  'hourly-summary',
  'hourly-summaries',
  'sdr',
  'query',
  'health',
  'washes',
]

const apiTarget = process.env.MONSOON_API ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: Object.fromEntries(API_PATHS.map((p) => [`/${p}`, apiTarget])),
  },
})
