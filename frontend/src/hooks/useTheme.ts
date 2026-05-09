import { useEffect, useState } from 'react'
import {
  applyTheme,
  getThemePref,
  resolveTheme,
  setThemePref,
  type ResolvedTheme,
  type ThemePref,
} from '../lib/theme'

/**
 * React hook for current theme + setter.
 *
 * Returns `{ pref, resolved, setPref }` where:
 * - `pref` is what user chose (system | light | dark)
 * - `resolved` is what's currently applied (light | dark) — useful for icon swaps
 * - `setPref` persists + re-applies
 *
 * Listens to `prefers-color-scheme` changes when pref is 'system'.
 */
export function useTheme(): {
  pref: ThemePref
  resolved: ResolvedTheme
  setPref: (p: ThemePref) => void
} {
  const [pref, setPrefState] = useState<ThemePref>(() => getThemePref())
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    resolveTheme(getThemePref()),
  )

  useEffect(() => {
    if (pref !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setResolved(applyTheme('system'))
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [pref])

  function setPref(p: ThemePref) {
    setPrefState(p)
    setThemePref(p)
    setResolved(resolveTheme(p))
  }

  return { pref, resolved, setPref }
}
