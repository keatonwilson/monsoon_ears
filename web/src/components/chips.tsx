// Pill chips replacing the inline-styled HTML spans from dashboard/style.py.

import { severityColor, sourceColor, sourceLabel, typeColor } from '@/lib/palette'

function Chip({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium text-white"
      style={{ backgroundColor: color }}
    >
      {text}
    </span>
  )
}

export function TypeChip({ type }: { type: string | null | undefined }) {
  if (!type) return null
  return <Chip text={type.toUpperCase()} color={typeColor(type)} />
}

export function SeverityChip({ severity }: { severity: string | null | undefined }) {
  if (!severity || severity === 'unknown') return null
  return <Chip text={severity.toUpperCase()} color={severityColor(severity)} />
}

export function SourceChip({ source }: { source: string | null | undefined }) {
  if (!source) return null
  return <Chip text={sourceLabel(source)} color={sourceColor(source)} />
}
