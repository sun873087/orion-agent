import { useEffect, useState } from 'react'
import {
  getThemePref,
  resolveTheme,
  setThemePref,
  subscribeTheme,
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
 * The OS-level prefers-color-scheme watcher lives at module level (started
 * from main.tsx via startSystemThemeWatcher); this hook only subscribes to
 * the resolved-theme channel so it re-renders whatever caller (e.g. icon)
 * needs the current value.
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

  useEffect(() => subscribeTheme(setResolved), [])

  function setPref(p: ThemePref) {
    setPrefState(p)
    setThemePref(p) // applyTheme runs inside → notifies subscribers → setResolved
  }

  return { pref, resolved, setPref }
}
