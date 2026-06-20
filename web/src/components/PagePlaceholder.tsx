import { EmptyState } from '@/components/EmptyState'

/** Stand-in for routes whose real page lands in a later PR. */
export function PagePlaceholder({ title }: { title: string }) {
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">{title}</h1>
      <EmptyState>This view is being ported from the Streamlit dashboard.</EmptyState>
    </div>
  )
}
