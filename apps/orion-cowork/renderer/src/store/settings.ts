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

/** TTS provider 偏好(Phase 31-T)。'off' = 完全停用按鈕,'web' = Web Speech API
 *  瀏覽器內建(免費),'openai' = cloud /audio/speech。 */
export type TtsProvider = 'off' | 'web' | 'openai'
export type OpenAiTtsModel = 'tts-1' | 'tts-1-hd'
export type OpenAiTtsVoice = 'alloy' | 'echo' | 'fable' | 'nova' | 'onyx' | 'shimmer'

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
  /** 動態 provider — models 是空 catalog,要 caller 跑 RPC(如 ollama.list_models)拿 */
  dynamic?: boolean
}

export type OllamaState = {
  /** 已 pull 的 model list(name + size + details);健康時非 null,失敗時 null */
  models: Array<{
    name: string
    size?: number
    details?: { parameter_size?: string; quantization_level?: string; family?: string }
  }> | null
  /** Ollama daemon 連線 OK 嗎 */
  ok: boolean
  /** Ollama daemon 沒開 / 連不上的錯誤訊息 */
  error: string | null
  /** 用的 base URL(顯示 / debug 用) */
  baseUrl: string
  /** 上次成功 fetch 的 epoch ms(用來判 stale) */
  lastFetched: number | null
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
  /** Ollama 動態 model list + daemon 狀態(Phase 31-L) */
  ollama: OllamaState
  refreshOllama: () => Promise<void>
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

  /** TTS 設定(Phase 31-T)。 */
  ttsProvider: TtsProvider
  setTtsProvider: (p: TtsProvider) => void
  ttsModel: OpenAiTtsModel
  setTtsModel: (m: OpenAiTtsModel) => void
  ttsVoice: OpenAiTtsVoice
  setTtsVoice: (v: OpenAiTtsVoice) => void
  ttsSpeed: number  // 0.25 ~ 4.0
  setTtsSpeed: (v: number) => void
  ttsAutoplay: boolean  // assistant 訊息 streaming 結束自動念
  setTtsAutoplay: (v: boolean) => void
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

  /** 同時 in-flight 的 conversation 上限(Phase 31-M)— 避免一次 spawn N 個
   *  session 同時串流推爆 token cost。預設 5,Settings UI 可調 1-20。 */
  maxConcurrentSessions: number
  setMaxConcurrentSessions: (v: number) => void

  /** 新 session 預設 budget cap(USD)— 累積 cost 超過自動 abort + 顯 banner。
   *  Phase 31-Q。0 = 不設限(預設,避免初次用就被擋)。Per-session 仍可在
   *  RightSidebar 各別調整;這只是新建 session 帶入的 default。 */
  defaultBudgetUsd: number
  setDefaultBudgetUsd: (v: number) => void

  /** Fork tree 已摺起的 parent session_id list(Phase 31-S 改 collapse 功能)。
   *  存 array 方便 persist。Sidebar render 時轉 Set 用。空 = 全展開(預設)。 */
  collapsedForkParents: string[]
  toggleForkCollapse: (sessionId: string) => void

  /** Compact 摘要要用的 (provider, model) — 通常用便宜 model 省 cost。
   *  null = 跟 chat 同一個 model(預設便宜:Anthropic→Haiku、OpenAI→gpt-5-mini)。 */
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
      ttsProvider: 'web',
      ttsModel: 'tts-1',
      ttsVoice: 'nova',
      ttsSpeed: 1.0,
      ttsAutoplay: false,
      providers: [],
      catalogLoaded: false,
      ollama: {
        models: null,
        ok: false,
        error: null,
        baseUrl: '',
        lastFetched: null,
      },
      refreshOllama: async () => {
        const { listOllamaModels } = await import('../api/agent')
        try {
          const result = await listOllamaModels()
          set({
            ollama: {
              models: result.models.map((m) => ({
                name: m.name,
                size: m.size,
                details: m.details,
              })),
              ok: true,
              error: null,
              baseUrl: result.base_url,
              lastFetched: Date.now(),
            },
          })
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e)
          set((prev) => ({
            ollama: {
              models: null,
              ok: false,
              error: msg,
              baseUrl: prev.ollama.baseUrl,
              lastFetched: Date.now(),
            },
          }))
        }
      },
      settingsOpen: false,
      activeSettingsSection: 'general',
      sidebarCollapsed: false,
      sidebarSearchOpen: false,
      sidebarSearchQuery: '',
      rightSidebarOpen: false,
      autoCompactEnabled: true,
      autoCompactThreshold: 0.8,
      maxConcurrentSessions: 5,
      defaultBudgetUsd: 0,
      collapsedForkParents: [],
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
      setTtsProvider: (p) => set({ ttsProvider: p }),
      setTtsModel: (m) => set({ ttsModel: m }),
      setTtsVoice: (v) => set({ ttsVoice: v }),
      setTtsSpeed: (v) => {
        const clamped = Math.max(0.25, Math.min(4.0, v))
        set({ ttsSpeed: Math.round(clamped * 100) / 100 })
      },
      setTtsAutoplay: (v) => set({ ttsAutoplay: v }),

      setCatalog: (providers) => set({ providers, catalogLoaded: true }),

      // Ollama refresh delegated to action defined above
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
      setMaxConcurrentSessions: (v) =>
        set({ maxConcurrentSessions: Math.max(1, Math.min(20, Math.round(v))) }),
      setDefaultBudgetUsd: (v) => {
        const n = Number.isFinite(v) ? Math.max(0, v) : 0
        // 1 美分精度
        set({ defaultBudgetUsd: Math.round(n * 100) / 100 })
      },
      toggleForkCollapse: (sessionId) => {
        set((s) => {
          const list = s.collapsedForkParents
          return list.includes(sessionId)
            ? { collapsedForkParents: list.filter((x) => x !== sessionId) }
            : { collapsedForkParents: [...list, sessionId] }
        })
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
        ttsProvider: s.ttsProvider,
        ttsModel: s.ttsModel,
        ttsVoice: s.ttsVoice,
        ttsSpeed: s.ttsSpeed,
        ttsAutoplay: s.ttsAutoplay,
        sidebarCollapsed: s.sidebarCollapsed,
        rightSidebarOpen: s.rightSidebarOpen,
        autoCompactEnabled: s.autoCompactEnabled,
        autoCompactThreshold: s.autoCompactThreshold,
        compactSummaryProvider: s.compactSummaryProvider,
        compactSummaryModel: s.compactSummaryModel,
        maxConcurrentSessions: s.maxConcurrentSessions,
        defaultBudgetUsd: s.defaultBudgetUsd,
        collapsedForkParents: s.collapsedForkParents,
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
