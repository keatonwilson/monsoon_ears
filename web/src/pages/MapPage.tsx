// Map — incident pins, APRS stations, Pima wash overlay (dashboard/tabs/map_view.py).
//
// The MapContainer must never remount: viewport (pan/zoom) is uncontrolled
// Leaflet state, and only the marker children re-render on refetch.

import { useMemo } from 'react'
import L from 'leaflet'
import { CircleMarker, GeoJSON, MapContainer, Marker, Popup, TileLayer, Tooltip } from 'react-leaflet'
import type { Feature } from 'geojson'

import 'leaflet/dist/leaflet.css'

import { useAprs, useEvents, useWashes } from '@/api/queries'
import { ErrorState } from '@/components/ErrorState'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { typeColor } from '@/lib/palette'
import { useBoolParam, useNumberParam } from '@/lib/urlState'

const TUCSON_CENTER: [number, number] = [32.22, -110.97]

// CARTO Positron — same basemap as the Folium dashboard.
const TILE_URL = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'

const iconCache = new Map<string, L.DivIcon>()

/** Colored pin using our exact hex palette (Folium had to downgrade to named colors). */
function pinIcon(color: string): L.DivIcon {
  let icon = iconCache.get(color)
  if (!icon) {
    icon = L.divIcon({
      className: '',
      html: `<span style="display:block;width:14px;height:14px;border-radius:50% 50% 50% 0;background:${color};border:1.5px solid white;transform:rotate(-45deg);box-shadow:0 1px 3px rgba(0,0,0,.4)"></span>`,
      iconSize: [14, 14],
      iconAnchor: [7, 14],
    })
    iconCache.set(color, icon)
  }
  return icon
}

const washStyle = { color: '#1e6091', weight: 2, opacity: 0.6 }

function washName(feature: Feature): string | null {
  const props = feature.properties ?? {}
  const key = Object.keys(props).find((k) => k.toUpperCase().includes('NAME'))
  return key ? String(props[key]) : null
}

export default function MapPage() {
  const [minutes, setMinutes] = useNumberParam('window', 6 * 60)
  const [aprsMinutes, setAprsMinutes] = useNumberParam('aprs_window', 30)
  const [showAprs, setShowAprs] = useBoolParam('aprs', true)
  const [showWashes, setShowWashes] = useBoolParam('washes', true)

  const events = useEvents({ since_minutes: minutes, limit: 500 })
  const aprs = useAprs({ minutes: aprsMinutes, limit: 300 })
  const washes = useWashes()

  const located = useMemo(
    () => (events.data?.results ?? []).filter((e) => e.lat != null && e.lon != null),
    [events.data],
  )
  const aprsLocated = useMemo(
    () => (aprs.data?.results ?? []).filter((a) => a.lat != null && a.lon != null),
    [aprs.data],
  )
  const skipped = (events.data?.results.length ?? 0) - located.length

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Map view</h1>

      <div className="flex flex-wrap items-end gap-6">
        <div className="w-56 space-y-2">
          <Label className="text-xs">
            Events from last {minutes >= 60 ? `${Math.round(minutes / 60)}h` : `${minutes}min`}
          </Label>
          <Slider min={15} max={24 * 60} step={15} value={[minutes]} onValueChange={([v]) => setMinutes(v)} />
        </div>
        <div className="w-56 space-y-2">
          <Label className="text-xs">APRS from last {aprsMinutes}min</Label>
          <Slider min={5} max={6 * 60} step={5} value={[aprsMinutes]} onValueChange={([v]) => setAprsMinutes(v)} />
        </div>
        <div className="flex items-center gap-2 pb-1">
          <Switch id="map-aprs" checked={showAprs} onCheckedChange={setShowAprs} />
          <Label htmlFor="map-aprs" className="text-xs">
            APRS stations
          </Label>
        </div>
        <div className="flex items-center gap-2 pb-1">
          <Switch id="map-washes" checked={showWashes} onCheckedChange={setShowWashes} />
          <Label htmlFor="map-washes" className="text-xs">
            Pima County washes
          </Label>
        </div>
      </div>

      {events.isError && <ErrorState error={events.error} />}

      <p className="text-xs text-muted-foreground">
        {located.length} voice incident{located.length === 1 ? '' : 's'}
        {showAprs && ` + ${aprsLocated.length} APRS station${aprsLocated.length === 1 ? '' : 's'}`} on
        map · {skipped} event{skipped === 1 ? '' : 's'} skipped (no geolocation yet)
        {showWashes && washes.data?.features.length === 0 && (
          <> · wash GeoJSON missing — run scripts/fetch_washes.py on the Pi</>
        )}
      </p>

      <div className="overflow-hidden rounded-lg border">
        <MapContainer center={TUCSON_CENTER} zoom={11} style={{ height: 650, width: '100%' }}>
          <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />

          {showWashes && washes.data && washes.data.features.length > 0 && (
            <GeoJSON
              data={washes.data}
              style={washStyle}
              onEachFeature={(feature, layer) => {
                const name = washName(feature)
                if (name) layer.bindTooltip(name)
              }}
            />
          )}

          {located.map((event) => (
            <Marker
              key={event.id}
              position={[event.lat!, event.lon!]}
              icon={pinIcon(typeColor(event.transmission_type))}
            >
              <Popup maxWidth={320}>
                <div className="space-y-1 text-xs">
                  <p>
                    <b>#{event.id}</b> · {event.transmission_type ?? 'unknown'}
                  </p>
                  <p className="italic">{(event.frequency_mhz ?? 0).toFixed(4)} MHz</p>
                  <p>{(event.corrected_text || event.raw_text || '').slice(0, 200)}</p>
                  {event.units && event.units.length > 0 && <p>units: {event.units.join(', ')}</p>}
                  {event.severity && event.severity !== 'unknown' && (
                    <p>
                      severity: <b>{event.severity}</b>
                    </p>
                  )}
                </div>
              </Popup>
            </Marker>
          ))}

          {showAprs &&
            aprsLocated.map((station) => (
              <CircleMarker
                key={station.id}
                center={[station.lat!, station.lon!]}
                radius={5}
                pathOptions={{ color: '#5cb85c', fillOpacity: 0.7 }}
              >
                <Tooltip>
                  {[
                    station.callsign,
                    station.temp_f != null ? `${station.temp_f.toFixed(0)}°F` : null,
                    station.rainfall_in != null ? `rain ${station.rainfall_in.toFixed(2)}in` : null,
                    station.wind_mph != null ? `wind ${station.wind_mph.toFixed(0)}mph` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </Tooltip>
              </CircleMarker>
            ))}
        </MapContainer>
      </div>
    </div>
  )
}
