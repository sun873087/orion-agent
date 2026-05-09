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

export function applyTheme(pref: ThemePref): ResolvedTheme {
  const resolved = resolveTheme(pref)
  const root = document.documentElement
  if (resolved === 'dark') root.classList.add('dark')
  else root.classList.remove('dark')
  return resolved
}
