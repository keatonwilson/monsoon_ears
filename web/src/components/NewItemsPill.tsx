import { ArrowUp } from 'lucide-react'

import { Button } from '@/components/ui/button'

/** Floating "N new" pill shown when a refetch landed while the user was busy. */
export function NewItemsPill({
  count,
  noun,
  onClick,
}: {
  count: number
  noun: string
  onClick: () => void
}) {
  if (count === 0) return null
  return (
    <div className="fixed bottom-6 left-1/2 z-40 -translate-x-1/2">
      <Button size="sm" className="rounded-full shadow-lg" onClick={onClick}>
        <ArrowUp className="size-4" />
        {count} new {noun}
        {count === 1 ? '' : 's'}
      </Button>
    </div>
  )
}
