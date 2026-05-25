import { create } from 'zustand'
import { apiFetch } from '../api/client'
import { detectDefaultLocale, isLocale, type Locale } from '../i18n/types'

/**
 * UI-level 跨元件狀態:locale / sidebar / settings modal。
 *
 * - locale 主來源是 localStorage(同步、離線可用、無 first-paint flash);
 *   setLocale 額外 best-effort PUT /me/settings/locale 做跨裝置同步,
 *   登入後 hydrateLocaleFromBackend() 把雲端值補回來。
 * - theme 不放這裡 — 它有 main.tsx 的 pre-paint apply 與 OS watcher,
 *   仍由 lib/theme.ts + useTheme 管理。
 */

const LOCALE_KEY = 'orion.locale'
const SIDEBAR_KEY = 'orion.sidebarCollapsed'
const AVATAR_KEY = 'orion.userAvatar'
/** user_settings 後端 key(跨裝置同步用);與 localStorage key 分開。 */
const LOCALE_SETTING = 'locale'

function initialLocale(): Locale {
  try {
    const v = localStorage.getItem(LOCALE_KEY)
    if (isLocale(v)) return v
  } catch {
    // private browsing 等 localStorage 失敗 — fallback 偵測
  }
  return detectDefaultLocale()
}

function initialSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === '1'
  } catch {
    return false
  }
}

function initialAvatar(): string | null {
  try {
    return localStorage.getItem(AVATAR_KEY)
  } catch {
    return null
  }
}

interface UiState {
  locale: Locale
  sidebarCollapsed: boolean
  settingsOpen: boolean
  /** 開 Settings 時要直接跳到哪個 tab(slash `/schedule`、Model 設定深連結用)。 */
  settingsTab: string | null
  /** 使用者頭像 / icon(data URL,localStorage;對齊 Cowork 的 userAvatar)。 */
  userAvatar: string | null
  setUserAvatar: (dataUrl: string | null) => void
  setLocale: (locale: Locale) => void
  hydrateLocaleFromBackend: () => Promise<void>
  toggleSidebar: () => void
  openSettings: (tab?: string) => void
  closeSettings: () => void
}

export const useUiStore = create<UiState>((set, get) => ({
  locale: initialLocale(),
  sidebarCollapsed: initialSidebarCollapsed(),
  settingsOpen: false,
  settingsTab: null,
  userAvatar: initialAvatar(),

  setUserAvatar: (dataUrl) => {
    set({ userAvatar: dataUrl })
    try {
      if (dataUrl) localStorage.setItem(AVATAR_KEY, dataUrl)
      else localStorage.removeItem(AVATAR_KEY)
    } catch {
      // localStorage 滿 / disabled — 忽略
    }
  },

  setLocale: (locale) => {
    set({ locale })
    try {
      localStorage.setItem(LOCALE_KEY, locale)
    } catch {
      // ignore
    }
    // 跨裝置同步;沒 DB(503)或網路失敗都不影響本機體驗
    void apiFetch(`/me/settings/${LOCALE_SETTING}`, {
      method: 'PUT',
      body: { value: locale },
    }).catch(() => {})
  },

  hydrateLocaleFromBackend: async () => {
    try {
      const all = await apiFetch<Record<string, unknown>>('/me/settings')
      const remote = all?.locale
      if (isLocale(remote) && remote !== get().locale) {
        set({ locale: remote })
        try {
          localStorage.setItem(LOCALE_KEY, remote)
        } catch {
          // ignore
        }
      }
    } catch {
      // 沒 DB / 未登入 — 維持本機 locale
    }
  },

  toggleSidebar: () => {
    const next = !get().sidebarCollapsed
    set({ sidebarCollapsed: next })
    try {
      localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0')
    } catch {
      // ignore
    }
  },

  openSettings: (tab) => set({ settingsOpen: true, settingsTab: tab ?? null }),
  closeSettings: () => set({ settingsOpen: false, settingsTab: null }),
}))
