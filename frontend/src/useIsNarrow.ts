/** True below the `md` breakpoint (768 px); used to pick the compact deck layout. */

import { useEffect, useState } from 'react'

const QUERY = '(max-width: 767px)'

export function useIsNarrow(): boolean {
  const supported = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  const [narrow, setNarrow] = useState(() => (supported ? window.matchMedia(QUERY).matches : false))

  useEffect(() => {
    if (!supported) return
    const media = window.matchMedia(QUERY)
    const update = (): void => setNarrow(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [supported])

  return narrow
}
