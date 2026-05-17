/**
 * Cowork agent state — zustand store。
 *
 * 一個 store 管:當前 session_id、訊息列表、busy 狀態、error。
 * Phase 31-C 範圍只有一個 session;multi-session 列表留 Phase 31-D 接持久化。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { AskQuestion, ContextBreakdown } from '../api/agent'

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

/** Backend 推來的 AskUserQuestion 請求 — 等 user 在 inline UI 答完才 resolve。 */
export type PendingQuestion = {
  /** 對應 sidecar 給的 request_id,reply RPC 用這個。 */
  requestId: string
  /** 出現在哪個 assistant message 內(inline render 在這 message 下方)。 */
  assistantId: string
  questions: AskQuestion[]
}

export type ToolCallState = {
  toolUseId: string
  toolName: string
  status: 'running' | 'success' | 'error' | 'awaiting_approval'
  /** Final result text (only set when status != 'running')。 */
  text: string
  /** 中間 progress events(可顯示 / 摺疊)。 */
  progress: string[]
  /** raw tool input(從 tool_start frame 拿到,給 UI 顯示「在跑什麼」)。 */
  input?: Record<string, unknown>
}

/** 歷史 hydrate 出來的 lazy attachment:沒有 previewUrl,要靠 ref lazy 拿。 */
export type AttachmentRef = {
  sessionId: string
  messageIndex: number
  attachmentIndex: number
}

export type AttachmentPreview = {
  /** data URL — user 剛 upload 的圖立即有;從歷史 hydrate 的圖一開始為 undefined,
   * MessageBubble 內 LazyImage 拿 ref 去 sidecar lazy fetch 後填入。 */
  previewUrl?: string
  filename: string
  media_type: string
  /** 歷史 attachment 才有;新上傳的 attachment 無 ref(已立即有 previewUrl)。 */
  ref?: AttachmentRef
}

/** 按 LLM emit 順序的 inline block — 讓 ToolCallGroup 出現在文字流的對位置。
 *  歷史 hydrate 出來的 message 沒這個欄位,UI fallback 純 text + toolCalls 渲染。
 */
export type AssistantBlock =
  | { type: 'text'; text: string }
  | { type: 'tools'; toolUseIds: string[] }

export type Message = {
  id: string
  role: MessageRole
  /** Plain text(user / assistant 全段彙整;歷史 hydrate 也用這個)。 */
  text: string
  /** assistant 訊息內附的工具呼叫(0..N)。 */
  toolCalls?: ToolCallState[]
  /** Streaming 時的 inline 順序;hydrate 歷史時不設,UI 走 fallback 舊式 layout。 */
  blocks?: AssistantBlock[]
  /** user message 上傳的附件(只用來 UI 顯示;base64 上傳已送 sidecar)。 */
  attachments?: AttachmentPreview[]
  /** 若 streaming 還沒結束就 true,UI 用來顯示 cursor。 */
  streaming?: boolean
  /** 系統訊息的特殊類型。 */
  kind?: 'compact-summary' | 'context-report'
  /** Compact summary card 才有:壓縮前的概略 token 數。 */
  beforeTokens?: number
  /** Context report card 才有:context window 分配資料。 */
  contextReport?: ContextBreakdown
  /** Compact 前的舊訊息 — UI 灰化,但仍 scroll 看得到(LLM 看不到)。 */
  compacted?: boolean
  /** 對齊 DB row 的 raw index — 由 _to_ui_messages_from_raw 給,edit/delete RPC 用。
   *  Live 串流出來的 message 沒有,要 reload 才會填上。 */
  messageIndex?: number
  createdAt: number
}

export type LoopStatus = {
  reason: string
  turns: number
} | null

export type SessionSummary = {
  session_id: string
  provider: string
  model: string
  title: string | null
  created_at: number
  n_messages: number
}

type AgentState = {
  sessionId: string | null
  messages: Message[]
  busy: boolean
  error: string | null
  lastLoopStatus: LoopStatus
  initError: string | null
  sessions: SessionSummary[]
  /** 當前等使用者回答的 AskUserQuestion(同時間只會有一個)。 */
  pendingQuestion: PendingQuestion | null
  /** 對話壓縮進行中(UI 顯 banner)。 */
  compacting: boolean
  setCompacting: (v: boolean) => void
  /** 非 tool call 產生但要顯在 RightSidebar 工作資料夾的檔/夾路徑。
   *  Per-session map(key=sessionId),切回來還看得到自己之前 /export 的紀錄。
   *  App 重啟才清(in-memory only,DB 不存 — Session 工作目錄裡的物理檔本來就在)。 */
  extraOutputFiles: Record<string, string[]>
  addExtraOutputFile: (sessionId: string, path: string) => void
  /** /context — push user msg "/context" + system context-report card 到 messages。
   *  不進 sidecar state_messages / DB,純 UI snapshot。 */
  appendContextReportCard: (report: ContextBreakdown) => void
  /** 壓縮完成 — 把現有訊息標 compacted(灰化,不再 LLM 可見)+ 插入 summary card。
   *  `liveTailCount` 是要保留不標 compacted 的尾端訊息數
   *  (auto 路徑為 2:剛 append 的 user msg + assistant skeleton;
   *   手動 /compact 為 0)。 */
  applyCompactComplete: (
    summary: string,
    beforeTokens: number,
    liveTailCount: number,
  ) => void

  // mutators
  setSessionId: (sid: string) => void
  setInitError: (err: string) => void
  setError: (err: string | null) => void
  setBusy: (b: boolean) => void
  setSessions: (s: SessionSummary[]) => void
  switchToSession: (sid: string) => void

  appendUserMessage: (text: string, attachments?: AttachmentPreview[]) => string
  /** 起 assistant 訊息槽位(streaming 即將開始),回傳 message id。 */
  beginAssistantMessage: () => string
  appendAssistantText: (id: string, delta: string) => void
  endAssistantMessage: (id: string) => void

  /** Tool 開始 — append 一個 toolCall 到當前正在 stream 的 assistant message。 */
  beginToolCall: (assistantId: string, call: Omit<ToolCallState, 'progress' | 'status' | 'text'>) => void
  appendToolProgress: (toolUseId: string, line: string) => void
  endToolCall: (toolUseId: string, payload: { isError: boolean; text: string }) => void
  /** Ask 模式 — 標記 toolCall 在等使用者 approval(顯 banner)。 */
  markToolAwaitingApproval: (toolUseId: string) => void
  /** User 已決 — 把 awaiting_approval 拉回 running,banner 立刻消失,
   *  之後 tool_result 來再走 endToolCall 改 success / error。 */
  clearToolApprovalUI: (toolUseId: string) => void

  setPendingQuestion: (q: PendingQuestion | null) => void

  finishLoop: (status: LoopStatus) => void
  reset: () => void
}

const newId = (() => {
  let n = 0
  return () => `m-${Date.now()}-${n++}`
})()

export const useAgentStore = create<AgentState>()(persist((set) => ({
  sessionId: null,
  messages: [],
  busy: false,
  error: null,
  lastLoopStatus: null,
  initError: null,
  sessions: [],
  pendingQuestion: null,
  compacting: false,
  extraOutputFiles: {},

  setSessionId: (sid) => set({ sessionId: sid }),
  setInitError: (err) => set({ initError: err }),
  setError: (err) => set({ error: err }),
  setBusy: (b) => set({ busy: b }),
  setSessions: (s) => set({ sessions: s }),
  switchToSession: (sid) =>
    set({
      sessionId: sid,
      messages: [],
      error: null,
      lastLoopStatus: null,
    }),

  appendUserMessage: (text, attachments) => {
    const id = newId()
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id,
          role: 'user',
          text,
          attachments: attachments && attachments.length ? attachments : undefined,
          createdAt: Date.now(),
        },
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
          blocks: [],
          streaming: true,
          createdAt: Date.now(),
        },
      ],
    }))
    return id
  },

  appendAssistantText: (id, delta) =>
    set((s) => ({
      messages: s.messages.map((m) => {
        if (m.id !== id) return m
        // text 仍 append 到 m.text(向後相容);同時 maintain blocks 順序
        const newText = m.text + delta
        const blocks = m.blocks ? [...m.blocks] : []
        const last = blocks[blocks.length - 1]
        if (last && last.type === 'text') {
          blocks[blocks.length - 1] = { type: 'text', text: last.text + delta }
        } else {
          blocks.push({ type: 'text', text: delta })
        }
        return { ...m, text: newText, blocks }
      }),
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
        // 維持 blocks 順序:碰到新 tool 且最後 block 不是 tools → 新開一個 tools block
        const blocks = m.blocks ? [...m.blocks] : []
        const last = blocks[blocks.length - 1]
        if (last && last.type === 'tools') {
          blocks[blocks.length - 1] = {
            type: 'tools',
            toolUseIds: [...last.toolUseIds, next.toolUseId],
          }
        } else {
          blocks.push({ type: 'tools', toolUseIds: [next.toolUseId] })
        }
        return {
          ...m,
          toolCalls: [...(m.toolCalls ?? []), next],
          blocks,
        }
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

  markToolAwaitingApproval: (toolUseId) =>
    set((s) => ({
      messages: s.messages.map((m) => ({
        ...m,
        toolCalls: (m.toolCalls ?? []).map((t) =>
          t.toolUseId === toolUseId && t.status === 'running'
            ? { ...t, status: 'awaiting_approval' }
            : t,
        ),
      })),
    })),

  clearToolApprovalUI: (toolUseId) =>
    set((s) => ({
      messages: s.messages.map((m) => ({
        ...m,
        toolCalls: (m.toolCalls ?? []).map((t) =>
          t.toolUseId === toolUseId && t.status === 'awaiting_approval'
            ? { ...t, status: 'running' }
            : t,
        ),
      })),
    })),

  setPendingQuestion: (q) => set({ pendingQuestion: q }),

  setCompacting: (v) => set({ compacting: v }),
  appendContextReportCard: (report) =>
    set((s) => {
      const now = Date.now()
      return {
        messages: [
          ...s.messages,
          {
            id: newId(),
            role: 'user',
            text: '/context',
            createdAt: now,
          },
          {
            id: newId(),
            role: 'system',
            text: '',
            kind: 'context-report',
            contextReport: report,
            createdAt: now + 1,
          },
        ],
      }
    }),

  addExtraOutputFile: (sessionId, path) =>
    set((s) => {
      const cur = s.extraOutputFiles[sessionId] ?? []
      if (cur.includes(path)) return s
      return {
        extraOutputFiles: {
          ...s.extraOutputFiles,
          [sessionId]: [...cur, path],
        },
      }
    }),
  applyCompactComplete: (summary, beforeTokens, liveTailCount) => {
    set((s) => {
      const all = s.messages
      const cut = Math.max(0, all.length - Math.max(0, liveTailCount))
      // 已是 compact-summary 的 row 不重複標,維持原 kind / compacted
      const compactedPrev = all.slice(0, cut).map((m) =>
        m.kind === 'compact-summary' ? m : { ...m, compacted: true },
      )
      const tail = all.slice(cut)
      const card: Message = {
        id: newId(),
        role: 'system',
        text: summary,
        kind: 'compact-summary',
        beforeTokens,
        createdAt: Date.now(),
      }
      return {
        messages: [...compactedPrev, card, ...tail],
        compacting: false,
      }
    })
  },

  finishLoop: (status) => set({ lastLoopStatus: status }),

  reset: () =>
    set({
      messages: [],
      busy: false,
      error: null,
      lastLoopStatus: null,
      pendingQuestion: null,
    }),
}), {
  name: 'orion-cowork-agent/v1',
  // 只 persist 跨 session / 跨 app 重啟有意義的 — extraOutputFiles 記 /export 結果,
  // 即便 app 重開,只要 .zip 物理檔還在 workspace,sidebar 仍會顯(useExistingFiles
  // 會 filter 掉已刪的孤兒)。其他 state 是 in-memory / 由 sidecar 重建,不存。
  partialize: (s) => ({
    extraOutputFiles: s.extraOutputFiles,
  }),
}))
