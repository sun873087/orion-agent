/**
 * Settings store — model 選擇 + 主題 + UI 偏好。
 *
 * Persistence:localStorage(rendererprocess 的 lightweight 持久化)。
 * 將來 Phase 31-D 接 sidecar keyring 後,API key 等敏感資料走 sidecar 不走這。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import { detectDefaultLocale, LOCALES, type Locale } from '../i18n/types'

export type Theme = 'dark' | 'light'
export type { Locale }

export type ModelEntry = {
  id: string
  label: string
  max_context_tokens?: number
  supports_reasoning?: boolean
  pricing?: Record<string, number>
}

export type Provider = {
  id: string
  label: string
  models: ModelEntry[]
  api_key_configured: boolean
}

type SettingsState = {
  // Persisted
  theme: Theme
  locale: Locale
  selectedProvider: string
  selectedModel: string
  // Ephemeral(load from sidecar on init)
  providers: Provider[]
  catalogLoaded: boolean
  settingsOpen: boolean
  /** 當前 Settings page 高亮的 section id。Page 是 list-driven 全頁,不再是 modal。 */
  activeSettingsSection: string

  /** Sidebar 收合(persist 到 localStorage)。 */
  sidebarCollapsed: boolean
  /** Sidebar 搜尋輸入框是否打開(ephemeral)。 */
  sidebarSearchOpen: boolean
  /** Sidebar 搜尋輸入內容(ephemeral)。 */
  sidebarSearchQuery: string

  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setLocale: (l: Locale) => void
  setSelectedModel: (provider: string, model: string) => void
  setCatalog: (providers: Provider[]) => void
  openSettings: (section?: string) => void
  closeSettings: () => void
  setActiveSettingsSection: (id: string) => void

  toggleSidebar: () => void
  toggleSidebarSearch: () => void
  setSidebarSearchQuery: (q: string) => void
}

const STORAGE_KEY = 'orion-cowork-settings/v1'

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      locale: detectDefaultLocale(),
      selectedProvider: 'anthropic',
      selectedModel: 'claude-sonnet-4-6',
      providers: [],
      catalogLoaded: false,
      settingsOpen: false,
      activeSettingsSection: 'appearance',
      sidebarCollapsed: false,
      sidebarSearchOpen: false,
      sidebarSearchQuery: '',

      setTheme: (t) => {
        set({ theme: t })
        applyTheme(t)
      },
      toggleTheme: () => {
        const next = get().theme === 'dark' ? 'light' : 'dark'
        set({ theme: next })
        applyTheme(next)
      },
      setLocale: (l) => {
        if (LOCALES.includes(l)) set({ locale: l })
      },

      setSelectedModel: (provider, model) =>
        set({ selectedProvider: provider, selectedModel: model }),

      setCatalog: (providers) => set({ providers, catalogLoaded: true }),
      openSettings: (section) =>
        set((s) => ({
          settingsOpen: true,
          activeSettingsSection: section ?? s.activeSettingsSection,
        })),
      closeSettings: () => set({ settingsOpen: false }),
      setActiveSettingsSection: (id) => set({ activeSettingsSection: id }),

      toggleSidebar: () =>
        set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      toggleSidebarSearch: () =>
        set((s) => ({
          // 開啟搜尋會順勢展開 sidebar(否則搜尋框看不到);關閉時清空 query
          sidebarSearchOpen: !s.sidebarSearchOpen,
          sidebarCollapsed: s.sidebarSearchOpen ? s.sidebarCollapsed : false,
          sidebarSearchQuery: s.sidebarSearchOpen ? '' : s.sidebarSearchQuery,
        })),
      setSidebarSearchQuery: (q) => set({ sidebarSearchQuery: q }),
    }),
    {
      name: STORAGE_KEY,
      partialize: (s) => ({
        theme: s.theme,
        locale: s.locale,
        selectedProvider: s.selectedProvider,
        selectedModel: s.selectedModel,
        sidebarCollapsed: s.sidebarCollapsed,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) applyTheme(state.theme)
      },
    },
  ),
)

function applyTheme(t: Theme) {
  const html = document.documentElement
  if (t === 'dark') html.classList.add('dark')
  else html.classList.remove('dark')
}
