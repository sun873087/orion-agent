/**
 * Theme persistence + DOM application.
 *
 * Three modes: 'system' (follow prefers-color-scheme), 'light', 'dark'.
 * 'system' is the default — matches Claude.ai and what user picked in Settings.
 *
 * Apply class to <html> rather than <body> so prose-msg / scrollbar inherit
 * before React renders. Init via `applyTheme(getThemePref())` in main.tsx
 * synchronously to avoid a flash of wrong theme on first paint.
 */

export type ThemePref = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'orion_theme'

export function getThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    // localStorage may throw in private browsing — silently fall back.
  }
  return 'system'
}

export function setThemePref(pref: ThemePref): void {
  try {
    localStorage.setItem(STORAGE_KEY, pref)
  } catch {
    // ignore
  }
  applyTheme(pref)
}

export function resolveTheme(pref: ThemePref): ResolvedTheme {
  if (pref === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light'
  }
  return pref
}

type ThemeListener = (resolved: ResolvedTheme) => void
const listeners = new Set<ThemeListener>()

/** Subscribe to resolved-theme changes (called whenever applyTheme runs). */
export function subscribeTheme(cb: ThemeListener): () => void {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

export function applyTheme(pref: ThemePref): ResolvedTheme {
  const resolved = resolveTheme(pref)
  const root = document.documentElement
  if (resolved === 'dark') root.classList.add('dark')
  else root.classList.remove('dark')
  for (const cb of listeners) cb(resolved)
  return resolved
}

let watcherStarted = false

/**
 * Set up a global listener for OS-level prefers-color-scheme changes.
 *
 * Idempotent — call once from main.tsx. When pref === 'system' and the OS
 * theme flips (e.g. user toggles macOS dark, or scheduled night mode kicks
 * in), this re-applies the theme so the app follows. Without this watcher
 * at module level, only SettingsPanel-mounted instances of useTheme would
 * react — and that's almost never (modal closed = no listener).
 */
export function startSystemThemeWatcher(): void {
  if (watcherStarted) return
  watcherStarted = true
  if (typeof window === 'undefined' || !window.matchMedia) return
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    if (getThemePref() === 'system') applyTheme('system')
  }
  mq.addEventListener('change', onChange)
}
