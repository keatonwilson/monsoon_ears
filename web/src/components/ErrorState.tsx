import { CircleAlert } from 'lucide-react'

/** Inline error panel — rendered in place of a section, never replaces the page. */
export function ErrorState({ title, error }: { title?: string; error: unknown }) {
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
      <CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
      <div>
        <p className="font-medium text-destructive">{title ?? 'Request failed'}</p>
        <p className="text-muted-foreground">{message}</p>
      </div>
    </div>
  )
}
