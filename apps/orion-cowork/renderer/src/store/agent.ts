import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { AskQuestion, ContextBreakdown } from '../api/agent'

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

/** 對 sidecar AskUserQuestionTool 的 pending 狀態。 */
export type PendingQuestion = {
  requestId: string
  /** 對應的 assistant message id(UI 把 banner 嵌進去那則 message)。 */
  assistantId: string
  questions: AskQuestion[]
}

export type ToolCallState = {
  toolUseId: string
  toolName: string
  status: 'running' | 'success' | 'error' | 'awaiting_approval'
  /** Final result text(success / error 時 set);running / awaiting_approval 時為空。 */
  text: string
  /** 中間 progress lines(可選)。 */
  progress: string[]
  /** Tool input(LLM 解析完整 JSON 後填,用於 inline preview)。 */
  input?: Record<string, unknown>
}

/** 對 sidecar 上 image attachment 的 ref(blob lazy load 用,base64 才不會塞 store)。 */
export type AttachmentRef = {
  sessionId: string
  messageIndex: number
  attachmentIndex: number
}

export type AttachmentPreview = {
  /** 上傳完成後仍要顯預覽:user message 沒 ref(尚未 persist),從 base64 來;
   * history reload 才走 ref + lazy fetch。 */
  previewUrl?: string
  filename: string
  media_type: string
  /** History 載回時拿到的 sidecar ref;send 後 backfill 進 user message。 */
  ref?: AttachmentRef
}

/** Assistant message 內的 block — 純文字 / tools 兩種。
 * 解 LLM 「stream text → 呼 tool → stream text → 呼 tool」交錯場景的順序。 */
export type AssistantBlock =
  | { type: 'text'; text: string }
  | { type: 'tools'; toolUseIds: string[] }

export type Message = {
  id: string
  role: MessageRole
  /** 顯示文字。Tool result 走 toolCalls;assistant text 仍寫這(blocks 順序由 blocks 顯)。 */
  text: string
  /** 若是 assistant message 含 tool calls,這 list 不為空。順序 = LLM emit 順序。 */
  toolCalls?: ToolCallState[]
  /** Inline rendering 順序 — text / tools 交錯。streaming 過程中 append。 */
  blocks?: AssistantBlock[]
  /** User message 上傳的圖。 */
  attachments?: AttachmentPreview[]
  /** Assistant 正在 stream 中(SDK 還沒 emit message_stop)。 */
  streaming?: boolean
  /** 系統卡(/compact summary / /context report 等)— 不送 LLM,純 UI。 */
  kind?: 'compact-summary' | 'context-report'
  /** Compact card 才有;顯示「省了多少 token」。 */
  beforeTokens?: number
  /** Context report card 才有。 */
  contextReport?: ContextBreakdown
  /** Compacted out 的舊 message(灰化顯示,LLM 不再看到)。 */
  compacted?: boolean
  /** Backfilled message_index(history reload 後 attachment ref / regenerate / delete-from 用)。 */
  messageIndex?: number
  /** Multi-pane DispatchPane:這條 user message 由 sibling pane 觸發(不是 user)。
   * MessageBubble 顯「from @backend (dispatch)」chip 取代 USER avatar。 */
  fromPane?: string
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
  starred?: boolean
  /** 排程觸發產生的 session 帶這個標記;手動建的 session 為 null。 */
  scheduled_by?: { schedule_id: string; schedule_name: string } | null
  /** Fork 系譜— 從哪個 session 第幾輪分叉來的,null = 非 fork。 */
  forked_from_session_id?: string | null
  forked_from_message_index?: number | null
}

/** Fork modal 開啟 request — App.tsx top-level 渲染 modal,MessageBubble 只 dispatch。
 * 改:原本 modal 在 MessageBubble 內 createPortal,user 回報沒反應;
 * 改提到 top-level 跟 NewProjectModal / PlanApprovalModal 同 pattern,徹底避開
 * ancestor CSS / event 干擾。 */
export type ForkRequest = {
  sessionId: string
  messageIndex: number
  /** Fork 點的訊息 role — 決定 modal 是問「新訊息」(user)或「標題」(assistant)。 */
  forkPointRole: 'user' | 'assistant'
  /** Fork 點原本的 user prompt 文字 — user 訊息 case 預填 / 提示用。 */
  originalText: string
} | null

type AgentState = {
  sessionId: string | null
  // ─── Per-session state— 切走的 session 仍然背景跑,events
  // 寫進對應 sid 的 slot,sidebar 顯 busy 指示。同時最多
  // `maxConcurrentSessions` 條 in-flight 串流(預設 5,可 Settings 調)。
  messagesBySession: Record<string, Message[]>
  busyBySession: Record<string, boolean>
  errorBySession: Record<string, string | null>
  lastLoopStatusBySession: Record<string, LoopStatus>
  pendingQuestionBySession: Record<string, PendingQuestion | null>
  compactingBySession: Record<string, boolean>
  initError: string | null
  sessions: SessionSummary[]
  /** Plan Mode— 每 session 一個 state,從 sidecar notification
   * 跟 plan_status RPC 同步。不存 localStorage,sidecar DB 是 source of truth。 */
  planModeStatusBySession: Record<string, 'idle' | 'pending' | 'active' | 'awaiting_approval'>
  setPlanModeStatus: (sid: string, status: 'idle' | 'pending' | 'active' | 'awaiting_approval') => void
  /** Plan AWAITING_APPROVAL 對話的 plan markdown(modal 用)。 */
  pendingPlanApprovalBySession: Record<string, {
    planId: string | null
    planMarkdown: string
    planFilePath: string | null
  }>
  setPendingPlanApproval: (sid: string, data: { planId: string | null; planMarkdown: string; planFilePath: string | null }) => void
  clearPendingPlanApproval: (sid: string) => void
  /** Fork modal 全域 state— 任意 MessageBubble 點分叉 dispatch
   * 進來,App.tsx 頂層渲染 ForkPromptModal,避開 chat 容器 CSS 影響。 */
  forkRequest: ForkRequest
  openForkRequest: (
    sessionId: string,
    messageIndex: number,
    forkPointRole: 'user' | 'assistant',
    originalText: string,
  ) => void
  closeForkRequest: () => void

  /** Sidebar 多選模式— 啟用時 row 顯 checkbox 取代 icon,
   * 點 row toggle 選取(不切 session)。退出時清空。Ephemeral,不 persist。 */
  sidebarSelectionMode: boolean
  selectedSessionIds: string[]
  enterSidebarSelection: () => void
  exitSidebarSelection: () => void
  toggleSessionSelected: (sid: string) => void
  selectAllSessions: (ids: string[]) => void
  clearSessionSelection: () => void
  /** 非 tool call 產生但要顯在 RightSidebar 工作資料夾的檔/夾路徑。
   * Per-session map(key=sessionId),切回來還看得到自己之前 /export 的紀錄。
   * App 重啟才清(in-memory only,DB 不存 — Session 工作目錄裡的物理檔本來就在)。 */
  extraOutputFiles: Record<string, string[]>
  addExtraOutputFile: (sessionId: string, path: string) => void
  /** /context — push user msg "/context" + system context-report card 到 messages。
   * 不進 sidecar state_messages / DB,純 UI snapshot。 */
  appendContextReportCard: (sid: string, report: ContextBreakdown) => void
  /** 壓縮完成 — 把現有訊息標 compacted(灰化,不再 LLM 可見)+ 插入 summary card。
   * `liveTailCount` 是要保留不標 compacted 的尾端訊息數
   * (auto 路徑為 2:剛 append 的 user msg + assistant skeleton;
   * 手動 /compact 為 0)。 */
  applyCompactComplete: (
    sid: string,
    summary: string,
    beforeTokens: number,
    liveTailCount: number,
  ) => void
  setCompacting: (sid: string, v: boolean) => void

  // mutators
  setSessionId: (sid: string) => void
  setInitError: (err: string) => void
  setError: (sid: string, err: string | null) => void
  setBusy: (sid: string, b: boolean) => void
  setSessions: (s: SessionSummary[]) => void
  /** Patch 單一 session 的 title — sidecar LLM 後補完自然標題後 push 過來。 */
  patchSessionTitle: (sid: string, title: string) => void
  /** 對話 follow-up 建議句 — 每 turn 完 sidecar 生 3 條,user 開始打字或送出
   * 訊息時就清掉。Per-session,切走的 session 仍保留自己的建議。 */
  followUpsBySession: Record<string, string[]>
  setFollowUps: (sid: string, suggestions: string[]) => void
  clearFollowUps: (sid: string) => void

  /** 輸入框草稿 — 切走 session 仍保留打到一半的文字,切回 hydrate。Per-session,
   * 送出 / 顯式清空後就清。In-memory only,sidecar 重啟 / Cowork 關閉再開會
   * 透過 localStorage hydrate(InputBox 自己處理) */
  draftsBySession: Record<string, string>
  setDraft: (sid: string, text: string) => void
  clearDraft: (sid: string) => void

  /** Message 👍 / 👎 feedback — assistant message 旁邊兩個按鈕,user 標完寫
   * DB 同時 ConversationSearch 排除 negative。Per-session per-message-id map。
   * Hydrate from DB on session load。 */
  feedbackBySession: Record<string, Record<string, 'positive' | 'negative'>>
  setMessageFeedback: (sid: string, messageId: string, feedback: 'positive' | 'negative' | null) => void
  hydrateFeedbackForSession: (sid: string, map: Record<string, 'positive' | 'negative'>) => void
  /** 切到某 session — **不**清舊 session 的 messages / busy,只改 currentSessionId。
   * 舊 session 仍可在背景跑,切回來能看到最新狀態。 */
  switchToSession: (sid: string) => void
  /** Hydrate 一個 session 的 messages(從 DB load 後初始化或刷新)。 */
  hydrateMessages: (sid: string, messages: Message[]) => void
  /** Truncate session messages 到某 index(regenerate / edit-from / delete-from 用)。 */
  truncateMessages: (sid: string, sliceEnd: number) => void
  /** 清掉某 session 的 in-memory state(delete session 時用)。 */
  clearSessionLocalState: (sid: string) => void

  appendUserMessage: (sid: string, text: string, attachments?: AttachmentPreview[]) => string
  /** 起 assistant 訊息槽位(streaming 即將開始),回傳 message id。 */
  beginAssistantMessage: (sid: string) => string
  appendAssistantText: (sid: string, id: string, delta: string) => void
  endAssistantMessage: (sid: string, id: string) => void

  /** Tool 開始 — append 一個 toolCall 到當前正在 stream 的 assistant message。 */
  beginToolCall: (sid: string, assistantId: string, call: Omit<ToolCallState, 'progress' | 'status' | 'text'>) => void
  appendToolProgress: (sid: string, toolUseId: string, line: string) => void
  endToolCall: (sid: string, toolUseId: string, payload: { isError: boolean; text: string }) => void
  /** Ask 模式 — 標記 toolCall 在等使用者 approval(顯 banner)。 */
  markToolAwaitingApproval: (sid: string, toolUseId: string) => void
  /** User 已決 — 把 awaiting_approval 拉回 running,banner 立刻消失,
   * 之後 tool_result 來再走 endToolCall 改 success / error。 */
  clearToolApprovalUI: (sid: string, toolUseId: string) => void

  setPendingQuestion: (sid: string, q: PendingQuestion | null) => void

  finishLoop: (sid: string, status: LoopStatus) => void

  /** Multi-pane collaboration — 開啟一個 collab window 時 session 切成「collab 視圖」,
   *  N 個 pane 並排。in-memory only,DB(cowork_collaborations)是 source of truth。
   *  null = 一般單 session view。 */
  currentCollaborationId: string | null
  collaborations: Array<{
    id: string
    name: string
    workspace_dir: string | null
    project_id: string | null
    budget_usd_cap: number | null
    panes: Array<{
      session_id: string
      pane_name: string
      pane_role: string | null
      pane_position: Record<string, unknown> | null
    }>
  }>
  setCollaborations: (items: AgentState['collaborations']) => void
  openCollaboration: (collaborationId: string | null) => void
  /** Active pane index within current collab view(焦點 pane,鍵盤輸入 → 它);
   *  null = 還沒 focus。 */
  activeCollabPaneIndex: number | null
  setActiveCollabPaneIndex: (index: number | null) => void

  /** 全清(logout / 災難用 — 不常用)。 */
  reset: () => void
}

const newId = (() => {
  let n = 0
  return () => `m-${Date.now()}-${n++}`
})()

/** 從 messagesBySession[sid] map 出新值的 helper — 沒 sid 直接 no-op。 */
function updateSession<K extends keyof AgentState>(
  state: AgentState,
  field: K,
  sid: string | null,
  updater: (prev: any) => any, // eslint-disable-line @typescript-eslint/no-explicit-any
): Partial<AgentState> {
  if (!sid) return {}
  const map = state[field] as Record<string, unknown>
  return { [field]: { ...map, [sid]: updater(map[sid]) } } as Partial<AgentState>
}

export const useAgentStore = create<AgentState>()(persist((set) => ({
  sessionId: null,
  messagesBySession: {},
  busyBySession: {},
  errorBySession: {},
  lastLoopStatusBySession: {},
  pendingQuestionBySession: {},
  compactingBySession: {},
  initError: null,
  sessions: [],
  planModeStatusBySession: {},
  pendingPlanApprovalBySession: {},
  extraOutputFiles: {},
  forkRequest: null,
  sidebarSelectionMode: false,
  selectedSessionIds: [],
  followUpsBySession: {},
  draftsBySession: {},
  feedbackBySession: {},

  setSessionId: (sid) => set({ sessionId: sid }),
  setInitError: (err) => set({ initError: err }),
  setError: (sid, err) =>
    set((s) => updateSession(s, 'errorBySession', sid, () => err)),
  setBusy: (sid, b) =>
    set((s) => updateSession(s, 'busyBySession', sid, () => b)),
  setSessions: (s) => set({ sessions: s }),
  patchSessionTitle: (sid, title) =>
    set((s) => ({
      sessions: s.sessions.map((row) =>
        row.session_id === sid ? { ...row, title } : row,
      ),
    })),
  setFollowUps: (sid, suggestions) =>
    set((s) => ({
      followUpsBySession: { ...s.followUpsBySession, [sid]: suggestions },
    })),
  clearFollowUps: (sid) =>
    set((s) => {
      if (s.followUpsBySession[sid] === undefined) return s
      const next = { ...s.followUpsBySession }
      delete next[sid]
      return { followUpsBySession: next }
    }),
  setDraft: (sid, text) =>
    set((s) => {
      if (s.draftsBySession[sid] === text) return s
      return { draftsBySession: { ...s.draftsBySession, [sid]: text } }
    }),
  clearDraft: (sid) =>
    set((s) => {
      if (s.draftsBySession[sid] === undefined) return s
      const next = { ...s.draftsBySession }
      delete next[sid]
      return { draftsBySession: next }
    }),
  setMessageFeedback: (sid, messageId, feedback) =>
    set((s) => {
      const sessionMap = { ...(s.feedbackBySession[sid] ?? {}) }
      if (feedback === null) {
        delete sessionMap[messageId]
      } else {
        sessionMap[messageId] = feedback
      }
      return {
        feedbackBySession: { ...s.feedbackBySession, [sid]: sessionMap },
      }
    }),
  hydrateFeedbackForSession: (sid, map) =>
    set((s) => ({
      feedbackBySession: { ...s.feedbackBySession, [sid]: map },
    })),
  switchToSession: (sid) => set({ sessionId: sid }),

  hydrateMessages: (sid, messages) =>
    set((s) => updateSession(s, 'messagesBySession', sid, () => messages)),

  truncateMessages: (sid, sliceEnd) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) =>
        (prev ?? []).slice(0, sliceEnd),
      ),
    ),

  clearSessionLocalState: (sid) =>
    set((s) => {
      const drop = <T extends Record<string, unknown>>(m: T): T => {
        const next = { ...m }
        delete next[sid]
        return next
      }
      return {
        messagesBySession: drop(s.messagesBySession),
        busyBySession: drop(s.busyBySession),
        errorBySession: drop(s.errorBySession),
        lastLoopStatusBySession: drop(s.lastLoopStatusBySession),
        pendingQuestionBySession: drop(s.pendingQuestionBySession),
        compactingBySession: drop(s.compactingBySession),
        followUpsBySession: drop(s.followUpsBySession),
        draftsBySession: drop(s.draftsBySession),
        feedbackBySession: drop(s.feedbackBySession),
      }
    }),

  appendUserMessage: (sid, text, attachments) => {
    const id = newId()
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) => [
        ...(prev ?? []),
        {
          id,
          role: 'user',
          text,
          attachments: attachments && attachments.length ? attachments : undefined,
          createdAt: Date.now(),
        },
      ]),
    )
    return id
  },

  beginAssistantMessage: (sid) => {
    const id = newId()
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) => [
        ...(prev ?? []),
        {
          id,
          role: 'assistant',
          text: '',
          toolCalls: [],
          blocks: [],
          streaming: true,
          createdAt: Date.now(),
        },
      ]),
    )
    return id
  },

  appendAssistantText: (sid, id, delta) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) =>
        (prev ?? []).map((m) => {
          if (m.id !== id) return m
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
      ),
    ),

  endAssistantMessage: (sid, id) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) =>
        (prev ?? []).map((m) => (m.id === id ? { ...m, streaming: false } : m)),
      ),
    ),

  beginToolCall: (sid, assistantId, call) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) =>
        (prev ?? []).map((m) => {
          if (m.id !== assistantId) return m
          const next: ToolCallState = {
            ...call,
            status: 'running',
            text: '',
            progress: [],
          }
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
      ),
    ),

  appendToolProgress: (sid, toolUseId, line) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) =>
        (prev ?? []).map((m) => ({
          ...m,
          toolCalls: (m.toolCalls ?? []).map((t) =>
            t.toolUseId === toolUseId
              ? { ...t, progress: [...t.progress, line] }
              : t,
          ),
        })),
      ),
    ),

  endToolCall: (sid, toolUseId, { isError, text }) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) =>
        (prev ?? []).map((m) => ({
          ...m,
          toolCalls: (m.toolCalls ?? []).map((t) =>
            t.toolUseId === toolUseId
              ? { ...t, status: isError ? 'error' : 'success', text }
              : t,
          ),
        })),
      ),
    ),

  markToolAwaitingApproval: (sid, toolUseId) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) =>
        (prev ?? []).map((m) => ({
          ...m,
          toolCalls: (m.toolCalls ?? []).map((t) =>
            t.toolUseId === toolUseId && t.status === 'running'
              ? { ...t, status: 'awaiting_approval' }
              : t,
          ),
        })),
      ),
    ),

  clearToolApprovalUI: (sid, toolUseId) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) =>
        (prev ?? []).map((m) => ({
          ...m,
          toolCalls: (m.toolCalls ?? []).map((t) =>
            t.toolUseId === toolUseId && t.status === 'awaiting_approval'
              ? { ...t, status: 'running' }
              : t,
          ),
        })),
      ),
    ),

  setPendingQuestion: (sid, q) =>
    set((s) => updateSession(s, 'pendingQuestionBySession', sid, () => q)),

  setPlanModeStatus: (sid, status) =>
    set((state) => ({
      planModeStatusBySession: { ...state.planModeStatusBySession, [sid]: status },
    })),
  setPendingPlanApproval: (sid, data) =>
    set((state) => ({
      pendingPlanApprovalBySession: { ...state.pendingPlanApprovalBySession, [sid]: data },
    })),
  clearPendingPlanApproval: (sid) =>
    set((state) => {
      const next = { ...state.pendingPlanApprovalBySession }
      delete next[sid]
      return { pendingPlanApprovalBySession: next }
    }),

  openForkRequest: (sessionId, messageIndex, forkPointRole, originalText) =>
    set({
      forkRequest: { sessionId, messageIndex, forkPointRole, originalText },
    }),
  closeForkRequest: () => set({ forkRequest: null }),

  // Multi-pane collaboration
  currentCollaborationId: null,
  collaborations: [],
  setCollaborations: (items) => set({ collaborations: items }),
  openCollaboration: (collaborationId) =>
    set({ currentCollaborationId: collaborationId, activeCollabPaneIndex: 0 }),
  activeCollabPaneIndex: null,
  setActiveCollabPaneIndex: (index) => set({ activeCollabPaneIndex: index }),

  enterSidebarSelection: () =>
    set({ sidebarSelectionMode: true, selectedSessionIds: [] }),
  exitSidebarSelection: () =>
    set({ sidebarSelectionMode: false, selectedSessionIds: [] }),
  toggleSessionSelected: (sid) =>
    set((s) => {
      const has = s.selectedSessionIds.includes(sid)
      return {
        selectedSessionIds: has
          ? s.selectedSessionIds.filter((x) => x !== sid)
          : [...s.selectedSessionIds, sid],
      }
    }),
  selectAllSessions: (ids) => set({ selectedSessionIds: ids }),
  clearSessionSelection: () => set({ selectedSessionIds: [] }),

  setCompacting: (sid, v) =>
    set((s) => updateSession(s, 'compactingBySession', sid, () => v)),
  appendContextReportCard: (sid, report) =>
    set((s) =>
      updateSession(s, 'messagesBySession', sid, (prev: Message[] | undefined) => {
        const now = Date.now()
        return [
          ...(prev ?? []),
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
        ]
      }),
    ),

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
  applyCompactComplete: (sid, summary, beforeTokens, liveTailCount) => {
    set((s) => {
      const all = s.messagesBySession[sid] ?? []
      const cut = Math.max(0, all.length - Math.max(0, liveTailCount))
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
        messagesBySession: {
          ...s.messagesBySession,
          [sid]: [...compactedPrev, card, ...tail],
        },
        compactingBySession: { ...s.compactingBySession, [sid]: false },
      }
    })
  },

  finishLoop: (sid, status) =>
    set((s) => updateSession(s, 'lastLoopStatusBySession', sid, () => status)),

  reset: () =>
    set({
      messagesBySession: {},
      busyBySession: {},
      errorBySession: {},
      lastLoopStatusBySession: {},
      pendingQuestionBySession: {},
      compactingBySession: {},
      currentCollaborationId: null,
      collaborations: [],
      activeCollabPaneIndex: null,
    }),
}), {
  name: 'orion-cowork-agent/v2',
  // 只 persist 跨 session / 跨 app 重啟有意義的 — extraOutputFiles 記 /export 結果,
  // 即便 app 重開,只要 .zip 物理檔還在 workspace,sidebar 仍會顯(useExistingFiles
  // 會 filter 掉已刪的孤兒)。其他 state 是 in-memory / 由 sidecar 重建,不存。
  partialize: (s) => ({
    extraOutputFiles: s.extraOutputFiles,
  }),
}))

// ─── Selector helpers — components 用這個 single-line 取 current session 的值 ────

/** 當前 session 的 messages(沒 sid 或 session 沒 hydrate 過回空 array)。 */
export function useCurrentMessages(): Message[] {
  return useAgentStore((s) =>
    s.sessionId ? s.messagesBySession[s.sessionId] ?? [] : [],
  )
}

/** 當前 session 是否在跑(LLM 還在 stream / tool 還沒完)。 */
export function useCurrentBusy(): boolean {
  return useAgentStore((s) =>
    s.sessionId ? s.busyBySession[s.sessionId] ?? false : false,
  )
}

export function useCurrentError(): string | null {
  return useAgentStore((s) =>
    s.sessionId ? s.errorBySession[s.sessionId] ?? null : null,
  )
}

export function useCurrentPendingQuestion(): PendingQuestion | null {
  return useAgentStore((s) =>
    s.sessionId ? s.pendingQuestionBySession[s.sessionId] ?? null : null,
  )
}

export function useCurrentCompacting(): boolean {
  return useAgentStore((s) =>
    s.sessionId ? s.compactingBySession[s.sessionId] ?? false : false,
  )
}

export function useCurrentLoopStatus(): LoopStatus {
  return useAgentStore((s) =>
    s.sessionId ? s.lastLoopStatusBySession[s.sessionId] ?? null : null,
  )
}

/** 多少 session 正在跑(用來判 concurrent limit)。 */
export function countRunningSessions(state: AgentState): number {
  return Object.values(state.busyBySession).filter(Boolean).length
}
