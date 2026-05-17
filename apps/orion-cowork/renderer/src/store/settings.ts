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

/**
 * Tool 動作許可模式 — 跟 Claude Cowork 的 Ask / Act 同概念。
 * - 'ask':每個 tool call 前 pause,user approve 才執行(尚未接 backend,顯示用)
 * - 'act':放手讓 agent 自己跑(目前實際行為)
 */
export type PermissionMode = 'ask' | 'act'

/** STT provider 偏好。'off' = 麥克風 disabled。 */
export type SttProvider = 'off' | 'openai' | 'google'

/** OpenAI STT model — 只 sttProvider='openai' 時生效。 */
export type OpenAiSttModel =
  | 'whisper-1'
  | 'gpt-4o-transcribe'
  | 'gpt-4o-mini-transcribe'

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
  /** 右側 detail panel(Progress / Working folder / Skills) */
  rightSidebarOpen: boolean

  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setLocale: (l: Locale) => void
  setSelectedModel: (provider: string, model: string) => void
  permissionMode: PermissionMode
  setPermissionMode: (m: PermissionMode) => void
  /** Data URL of user avatar(JPEG, 256x256 resized);null = 用 fallback icon。 */
  userAvatar: string | null
  setUserAvatar: (dataUrl: string | null) => void
  sttProvider: SttProvider
  setSttProvider: (p: SttProvider) => void
  openaiSttModel: OpenAiSttModel
  setOpenaiSttModel: (m: OpenAiSttModel) => void
  setCatalog: (providers: Provider[]) => void
  openSettings: (section?: string) => void
  closeSettings: () => void
  setActiveSettingsSection: (id: string) => void

  toggleSidebar: () => void
  toggleSidebarSearch: () => void
  setSidebarSearchQuery: (q: string) => void
  toggleRightSidebar: () => void

  /** 自動壓縮對話歷史 — context 用量超過 threshold 時觸發。 */
  autoCompactEnabled: boolean
  /** Auto-compact 觸發比例(0.1~0.99,預設 0.8 = 80%)。 */
  autoCompactThreshold: number
  setAutoCompactEnabled: (v: boolean) => void
  setAutoCompactThreshold: (v: number) => void

  /** Compact 摘要要用的 (provider, model) — 通常用便宜 model 省 cost。
   *  null = 跟 chat 同一個 model(預設便宜:Anthropic→Haiku、OpenAI→gpt-4o-mini)。 */
  compactSummaryProvider: string | null
  compactSummaryModel: string | null
  setCompactSummary: (provider: string | null, model: string | null) => void

  /** 當前選中的 project filter。null = 不 filter(顯所有 sessions)。 */
  activeProjectId: string | null
  /** New Project modal 開關。 */
  newProjectOpen: boolean
  /** 編輯 project 的 id;null = 沒在編。 */
  editingProjectId: string | null

  setActiveProjectId: (id: string | null) => void
  openNewProject: () => void
  closeNewProject: () => void
  openEditProject: (id: string) => void
  closeEditProject: () => void
}

const STORAGE_KEY = 'orion-cowork-settings/v1'

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      locale: detectDefaultLocale(),
      selectedProvider: 'anthropic',
      selectedModel: 'claude-sonnet-4-6',
      permissionMode: 'act',
      userAvatar: null,
      sttProvider: 'openai',
      openaiSttModel: 'gpt-4o-mini-transcribe',
      providers: [],
      catalogLoaded: false,
      settingsOpen: false,
      activeSettingsSection: 'general',
      sidebarCollapsed: false,
      sidebarSearchOpen: false,
      sidebarSearchQuery: '',
      rightSidebarOpen: false,
      autoCompactEnabled: true,
      autoCompactThreshold: 0.8,
      // 預設用便宜 model 摘要(Anthropic 端 Haiku),省 cost ~5x。
      // 跟 chat provider 對齊在 dispatch 時挑;User 也可手動改成任何 model。
      compactSummaryProvider: 'anthropic',
      compactSummaryModel: 'claude-haiku-4-5',
      activeProjectId: null,
      newProjectOpen: false,
      editingProjectId: null,

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
      setPermissionMode: (m) => set({ permissionMode: m }),
      setUserAvatar: (d) => set({ userAvatar: d }),
      setSttProvider: (p) => set({ sttProvider: p }),
      setOpenaiSttModel: (m) => set({ openaiSttModel: m }),

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
      toggleRightSidebar: () =>
        set((s) => ({ rightSidebarOpen: !s.rightSidebarOpen })),

      setAutoCompactEnabled: (v) => set({ autoCompactEnabled: v }),
      setAutoCompactThreshold: (v) => {
        const clamped = Math.min(0.99, Math.max(0.1, v))
        set({ autoCompactThreshold: Math.round(clamped * 100) / 100 })
      },
      setCompactSummary: (provider, model) =>
        set({ compactSummaryProvider: provider, compactSummaryModel: model }),

      setActiveProjectId: (id) => set({ activeProjectId: id }),
      openNewProject: () => set({ newProjectOpen: true }),
      closeNewProject: () => set({ newProjectOpen: false }),
      openEditProject: (id) => set({ editingProjectId: id }),
      closeEditProject: () => set({ editingProjectId: null }),
    }),
    {
      name: STORAGE_KEY,
      partialize: (s) => ({
        theme: s.theme,
        locale: s.locale,
        selectedProvider: s.selectedProvider,
        selectedModel: s.selectedModel,
        permissionMode: s.permissionMode,
        userAvatar: s.userAvatar,
        sttProvider: s.sttProvider,
        openaiSttModel: s.openaiSttModel,
        sidebarCollapsed: s.sidebarCollapsed,
        rightSidebarOpen: s.rightSidebarOpen,
        autoCompactEnabled: s.autoCompactEnabled,
        autoCompactThreshold: s.autoCompactThreshold,
        compactSummaryProvider: s.compactSummaryProvider,
        compactSummaryModel: s.compactSummaryModel,
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
