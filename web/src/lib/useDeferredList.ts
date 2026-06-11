// The anti-jump half of the no-interruption contract for polled lists.
//
// While the user is "engaged" (a row expanded, or scrolled into the list) a
// background refetch must not reorder rows under them. Fresh data is parked
// and surfaced through a "N new" pill; clicking the pill (or disengaging at
// the top of the page) swaps it in. Filter changes always swap immediately.

import { useCallback, useEffect, useRef, useState } from 'react'

const SCROLL_ENGAGED_PX = 150

export function useDeferredList<T extends { id: number }>(
  fresh: T[] | undefined,
  paramsKey: string,
  engaged: boolean,
): { rows: T[] | undefined; pendingCount: number; showPending: () => void } {
  const [displayed, setDisplayed] = useState<T[] | undefined>(undefined)
  const lastParamsKey = useRef(paramsKey)

  useEffect(() => {
    if (!fresh) return
    const paramsChanged = lastParamsKey.current !== paramsKey
    lastParamsKey.current = paramsKey
    const scrolled = window.scrollY > SCROLL_ENGAGED_PX
    if (paramsChanged || displayed === undefined || (!engaged && !scrolled)) {
      setDisplayed(fresh)
    }
    // `displayed` is intentionally read but not depended on: this effect only
    // reacts to new data or filter changes, never to its own swap.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fresh, paramsKey, engaged])

  const showPending = useCallback(() => {
    if (fresh) setDisplayed(fresh)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [fresh])

  const rows = displayed ?? fresh
  let pendingCount = 0
  if (fresh && displayed && fresh !== displayed) {
    const shown = new Set(displayed.map((row) => row.id))
    pendingCount = fresh.filter((row) => !shown.has(row.id)).length
  }

  return { rows, pendingCount, showPending }
}
