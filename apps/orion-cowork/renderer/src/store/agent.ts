/**
 * Cowork agent state — zustand store。
 *
 * 一個 store 管:當前 session_id、訊息列表、busy 狀態、error。
 * Phase 31-C 範圍只有一個 session;multi-session 列表留 Phase 31-D 接持久化。
 */

import { create } from 'zustand'

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

export type ToolCallState = {
  toolUseId: string
  toolName: string
  status: 'running' | 'success' | 'error'
  /** Final result text (only set when status != 'running')。 */
  text: string
  /** 中間 progress events(可顯示 / 摺疊)。 */
  progress: string[]
}

export type Message = {
  id: string
  role: MessageRole
  /** Plain text(user / assistant)。tool message 用 toolCalls 顯示。 */
  text: string
  /** assistant 訊息內附的工具呼叫(0..N)。 */
  toolCalls?: ToolCallState[]
  /** 若 streaming 還沒結束就 true,UI 用來顯示 cursor。 */
  streaming?: boolean
  createdAt: number
}

export type LoopStatus = {
  reason: string
  turns: number
} | null

type AgentState = {
  sessionId: string | null
  messages: Message[]
  busy: boolean
  error: string | null
  lastLoopStatus: LoopStatus
  initError: string | null

  // mutators
  setSessionId: (sid: string) => void
  setInitError: (err: string) => void
  setError: (err: string | null) => void
  setBusy: (b: boolean) => void

  appendUserMessage: (text: string) => string
  /** 起 assistant 訊息槽位(streaming 即將開始),回傳 message id。 */
  beginAssistantMessage: () => string
  appendAssistantText: (id: string, delta: string) => void
  endAssistantMessage: (id: string) => void

  /** Tool 開始 — append 一個 toolCall 到當前正在 stream 的 assistant message。 */
  beginToolCall: (assistantId: string, call: Omit<ToolCallState, 'progress' | 'status' | 'text'>) => void
  appendToolProgress: (toolUseId: string, line: string) => void
  endToolCall: (toolUseId: string, payload: { isError: boolean; text: string }) => void

  finishLoop: (status: LoopStatus) => void
  reset: () => void
}

const newId = (() => {
  let n = 0
  return () => `m-${Date.now()}-${n++}`
})()

export const useAgentStore = create<AgentState>((set, get) => ({
  sessionId: null,
  messages: [],
  busy: false,
  error: null,
  lastLoopStatus: null,
  initError: null,

  setSessionId: (sid) => set({ sessionId: sid }),
  setInitError: (err) => set({ initError: err }),
  setError: (err) => set({ error: err }),
  setBusy: (b) => set({ busy: b }),

  appendUserMessage: (text) => {
    const id = newId()
    set((s) => ({
      messages: [
        ...s.messages,
        { id, role: 'user', text, createdAt: Date.now() },
      ],
    }))
    return id
  },

  beginAssistantMessage: () => {
    const id = newId()
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id,
          role: 'assistant',
          text: '',
          toolCalls: [],
          streaming: true,
          createdAt: Date.now(),
        },
      ],
    }))
    return id
  },

  appendAssistantText: (id, delta) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, text: m.text + delta } : m,
      ),
    })),

  endAssistantMessage: (id) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, streaming: false } : m,
      ),
    })),

  beginToolCall: (assistantId, call) =>
    set((s) => ({
      messages: s.messages.map((m) => {
        if (m.id !== assistantId) return m
        const next: ToolCallState = {
          ...call,
          status: 'running',
          text: '',
          progress: [],
        }
        return { ...m, toolCalls: [...(m.toolCalls ?? []), next] }
      }),
    })),

  appendToolProgress: (toolUseId, line) =>
    set((s) => ({
      messages: s.messages.map((m) => ({
        ...m,
        toolCalls: (m.toolCalls ?? []).map((t) =>
          t.toolUseId === toolUseId
            ? { ...t, progress: [...t.progress, line] }
            : t,
        ),
      })),
    })),

  endToolCall: (toolUseId, { isError, text }) =>
    set((s) => ({
      messages: s.messages.map((m) => ({
        ...m,
        toolCalls: (m.toolCalls ?? []).map((t) =>
          t.toolUseId === toolUseId
            ? { ...t, status: isError ? 'error' : 'success', text }
            : t,
        ),
      })),
    })),

  finishLoop: (status) => set({ lastLoopStatus: status }),

  reset: () =>
    set({
      messages: [],
      busy: false,
      error: null,
      lastLoopStatus: null,
    }),
}))
