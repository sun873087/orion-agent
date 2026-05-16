/**
 * Settings store — model 選擇 + 主題 + UI 偏好。
 *
 * Persistence:localStorage(rendererprocess 的 lightweight 持久化)。
 * 將來 Phase 31-D 接 sidecar keyring 後,API key 等敏感資料走 sidecar 不走這。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'dark' | 'light'

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
  selectedProvider: string
  selectedModel: string
  // Ephemeral(load from sidecar on init)
  providers: Provider[]
  catalogLoaded: boolean

  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setSelectedModel: (provider: string, model: string) => void
  setCatalog: (providers: Provider[]) => void
}

const STORAGE_KEY = 'orion-cowork-settings/v1'

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      selectedProvider: 'anthropic',
      selectedModel: 'claude-sonnet-4-6',
      providers: [],
      catalogLoaded: false,

      setTheme: (t) => {
        set({ theme: t })
        applyTheme(t)
      },
      toggleTheme: () => {
        const next = get().theme === 'dark' ? 'light' : 'dark'
        set({ theme: next })
        applyTheme(next)
      },

      setSelectedModel: (provider, model) =>
        set({ selectedProvider: provider, selectedModel: model }),

      setCatalog: (providers) => set({ providers, catalogLoaded: true }),
    }),
    {
      name: STORAGE_KEY,
      partialize: (s) => ({
        theme: s.theme,
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
