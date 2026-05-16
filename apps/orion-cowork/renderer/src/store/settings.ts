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
  languagePanelOpen: boolean

  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setLocale: (l: Locale) => void
  setSelectedModel: (provider: string, model: string) => void
  setCatalog: (providers: Provider[]) => void
  openSettings: () => void
  closeSettings: () => void
  openLanguagePanel: () => void
  closeLanguagePanel: () => void
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
      languagePanelOpen: false,

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
      openSettings: () => set({ settingsOpen: true }),
      closeSettings: () => set({ settingsOpen: false }),
      openLanguagePanel: () => set({ languagePanelOpen: true }),
      closeLanguagePanel: () => set({ languagePanelOpen: false }),
    }),
    {
      name: STORAGE_KEY,
      partialize: (s) => ({
        theme: s.theme,
        locale: s.locale,
        selectedProvider: s.selectedProvider,
        selectedModel: s.selectedModel,
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
