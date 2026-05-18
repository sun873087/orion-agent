/**
 * Bridge:window.agent.call(...) → zustand store。
 *
 * - useInitConversation:app 啟動時建 conversation_id(once)
 * - useSendPrompt:接 InputBox 的 send,把事件流灌進 store
 * - useAbort:中止當前 turn
 */

import { useCallback, useEffect } from 'react'

import {
  abort as rpcAbort,
  compactConversation as rpcCompact,
  createConversation,
  deleteConversation as rpcDelete,
  listConversations,
  loadMessages,
  regenerateLast,
  sendPrompt as rpcSendPrompt,
  truncateConversation as rpcTruncate,
  type Attachment,
  type LoadedMessage,
  type SidecarEvent,
} from '../api/agent'
import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

async function refreshSessions() {
  try {
    const list = await listConversations()
    useAgentStore.getState().setSessions(list)
  } catch {
    // 忽略 — 列表更新失敗不該擋住流程
  }
}

/**
 * 啟動時 refresh sidebar 的 sessions 列表(從 DB)。不再 auto-create — 等
 * user 真的送 prompt 才會建新 session(lazy create,Phase 31-D 後修)。
 */
export function useInitConversation() {
  useEffect(() => {
    refreshSessions()
  }, [])
}

/**
 * 訂閱 sidecar 推的 scheduler.fired — 排程觸發生 session 後 refresh sidebar
 * 讓使用者看到 scheduled badge。
 */
export function useScheduleNotifications() {
  useEffect(() => {
    if (!window.schedulerApi?.onFired) return
    const off = window.schedulerApi.onFired((data) => {
      // 排程剛建立的 session 還在跑 LLM,sidebar 應立刻顯示
      refreshSessions()
      // Loop fire 時 sidecar 把 messages 寫進 DB,但 messagesBySession[sid]
      // 在 renderer 已有舊資料 → useSwitchConversation 也跳過 reload(避免
      // 覆蓋 in-flight 進度)。Loop 結束後 fire 通知是 trigger reload 的最
      // 好時機:若 session 已 hydrate 過(user 看過),重 load 新訊息;沒
      // hydrate 過則跳過,user 切過去時自然會 load。
      const sid = data.session_id
      if (sid) {
        const existing = useAgentStore.getState().messagesBySession[sid]
        if (existing !== undefined) {
          void (async () => {
            try {
              const loaded = await loadMessages(sid)
              _hydrateMessages(sid, loaded)
            } catch {
              // sidecar 暫時不可達或 race — 不打擾 user,下次切 session 會補
            }
          })()
        }
      }
      // 對應 OS notification(若 user 授權)
      try {
        if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
          const title = data.status === 'error'
            ? `排程 "${data.schedule_name}" 失敗`
            : `排程 "${data.schedule_name}" 已執行`
          const body = data.status === 'error'
            ? (data.error ?? '請查看詳細紀錄')
            : '對話已加入側邊欄'
          new Notification(title, { body, silent: true })
        }
      } catch {
        // 沒 Notification API 也沒事
      }
    })
    return off
  }, [])
}

/**
 * Session 切換時呼 conversation.plan_status,re-hydrate plan mode UI。
 * 用於 crash recovery / 切回有 AWAITING_APPROVAL 的 session。
 */
export function usePlanStatusRehydrate(): void {
  const sid = useAgentStore((s) => s.sessionId)
  useEffect(() => {
    if (!sid) return
    let cancelled = false
    void (async () => {
      try {
        const { planStatus } = await import('../api/agent')
        const result = await planStatus(sid)
        if (cancelled) return
        const store = useAgentStore.getState()
        store.setPlanModeStatus(sid, result.status)
        if (result.status === 'awaiting_approval' && result.plan_markdown) {
          store.setPendingPlanApproval(sid, {
            planId: result.plan_id,
            planMarkdown: result.plan_markdown,
            planFilePath: result.plan_file_path,
          })
        } else {
          store.clearPendingPlanApproval(sid)
        }
      } catch {
        // 沒這 method / sidecar 還沒起 — 略過,notification 之後會補
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sid])
}

/**
 * 訂閱 sidecar 推的 plan_mode.* 事件,同步 renderer store。
 * Phase 31-J — Plan Mode UI 反應 sidecar 狀態變化。
 */
export function usePlanModeNotifications(): void {
  useEffect(() => {
    if (!window.planApi) return
    const offAwaiting = window.planApi.onAwaitingApproval((data) => {
      useAgentStore.getState().setPlanModeStatus(data.session_id, 'awaiting_approval')
      useAgentStore.getState().setPendingPlanApproval(data.session_id, {
        planId: data.plan_id,
        planMarkdown: data.plan_markdown || '',
        planFilePath: data.plan_file_path,
      })
    })
    const offEntered = window.planApi.onEntered((data) => {
      useAgentStore.getState().setPlanModeStatus(data.session_id, 'pending')
    })
    const offExited = window.planApi.onExited((data) => {
      useAgentStore.getState().setPlanModeStatus(data.session_id, 'idle')
      useAgentStore.getState().clearPendingPlanApproval(data.session_id)
    })
    const offApproved = window.planApi.onApproved((data) => {
      useAgentStore.getState().setPlanModeStatus(data.session_id, 'idle')
      useAgentStore.getState().clearPendingPlanApproval(data.session_id)
    })
    const offRejected = window.planApi.onRejected((data) => {
      useAgentStore.getState().setPlanModeStatus(data.session_id, 'idle')
      useAgentStore.getState().clearPendingPlanApproval(data.session_id)
    })
    return () => {
      offAwaiting()
      offEntered()
      offExited()
      offApproved()
      offRejected()
    }
  }, [])
}

/**
 * 訂閱 sidecar 推的 budget.exceeded 事件(Phase 31-Q)。
 *
 * 累積成本超 cap 時 sidecar 會 emit 一次(設新 cap 後才會再 emit)。
 * 這邊把訊息塞進對應 session 的 errorBySession,UI 顯紅 banner。
 */
export function useBudgetNotifications(): void {
  useEffect(() => {
    if (!window.budgetApi) return
    const off = window.budgetApi.onExceeded((data) => {
      const cur = data.current_usd.toFixed(4)
      const cap = data.budget_usd_cap.toFixed(2)
      useAgentStore.getState().setError(
        data.session_id,
        `Session 累積成本超過上限($${cur} / $${cap})— 右側面板可調整 cap 後繼續。`,
      )
    })
    return () => off()
  }, [])
}

/**
 * "New chat" 按鈕。只清 currentSessionId,不立即建 DB session。首次 send 時
 * useSendPrompt 偵測 sessionId==null 才呼叫 createConversation。
 *
 * 其他 session 的 messages / busy / pendingQuestion 仍留在 store 內背景跑,
 * 切回去時 instantly visible(Phase 31-M)。
 */
export function useNewConversation() {
  return useCallback(() => {
    useAgentStore.setState({ sessionId: null })
  }, [])
}

export function useSwitchConversation() {
  return useCallback(async (sid: string) => {
    const store = useAgentStore.getState()
    store.switchToSession(sid)
    // 若已 hydrate 過(背景跑著的 session)跳過 reload,避免覆蓋 in-flight 進度
    const existing = useAgentStore.getState().messagesBySession[sid]
    if (existing && existing.length > 0) return
    try {
      const loaded = await loadMessages(sid)
      _hydrateMessages(sid, loaded)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(sid, `failed to load history: ${msg}`)
    }
  }, [])
}

function _hydrateMessages(sessionId: string, loaded: LoadedMessage[]) {
  // Reset 後重 build store.messages — attachment 只帶 ref,base64 由
  // MessageBubble.LazyImage 之後 useEffect 拿,不擋切換 latency。
  // Tool calls / blocks 也 hydrate,讓 RightSidebar 跟 inline file card
  // 在歷史對話也能 work。
  let counter = 0
  const messages = loaded.map((m) => ({
    id: `hist-${Date.now()}-${counter++}`,
    role: m.role,
    text: m.text,
    attachments: m.attachments.length
      ? m.attachments.map((a, i) => ({
          previewUrl: undefined,
          filename: `attachment-${i + 1}`,
          media_type: a.media_type,
          ref: {
            sessionId,
            messageIndex: a.ref.message_index,
            attachmentIndex: a.ref.attachment_index,
          },
        }))
      : undefined,
    toolCalls: m.tool_calls?.length
      ? m.tool_calls.map((t) => ({
          toolUseId: t.tool_use_id,
          toolName: t.tool_name,
          input: t.input,
          status: t.status as 'success' | 'error',
          text: t.text,
          progress: [] as string[],
        }))
      : undefined,
    blocks: m.blocks?.length
      ? m.blocks.map((b) =>
          b.type === 'text'
            ? { type: 'text' as const, text: b.text }
            : { type: 'tools' as const, toolUseIds: b.tool_use_ids },
        )
      : undefined,
    compacted: m.compacted || undefined,
    kind: m.kind,
    beforeTokens: m.before_tokens,
    messageIndex: m.message_index,
    createdAt: Date.now(),
  }))
  useAgentStore.getState().hydrateMessages(sessionId, messages)
}

export function useRegenerate() {
  return useCallback(async () => {
    const store = useAgentStore.getState()
    const sid = store.sessionId
    if (!sid) return
    if (store.busyBySession[sid]) return

    // Drop last assistant message (UI) — sidecar 同時 truncate DB + state
    const msgs = store.messagesBySession[sid] ?? []
    let lastUserIdx = -1
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'user') {
        lastUserIdx = i
        break
      }
    }
    if (lastUserIdx < 0) return
    store.truncateMessages(sid, lastUserIdx + 1)

    const assistantId = store.beginAssistantMessage(sid)
    store.setError(sid, null)
    store.setBusy(sid, true)
    try {
      await regenerateLast(sid, (ev: SidecarEvent) => applyEvent(sid, assistantId, ev))
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(sid, msg)
    } finally {
      useAgentStore.getState().endAssistantMessage(sid, assistantId)
      useAgentStore.getState().setBusy(sid, false)
      refreshSessions()
      if (sid) void backfillMessageIndices(sid)
    }
  }, [])
}

export function useDeleteConversation() {
  return useCallback(async (sid: string) => {
    try {
      await rpcDelete(sid)
      const state = useAgentStore.getState()
      // 若刪的是當前 session,清空 sessionId(下個 init 或 new 觸發 create)
      if (state.sessionId === sid) {
        useAgentStore.setState({ sessionId: null })
      }
      // 清掉這 session 的 in-memory state(messages / busy / pendingQuestion 等)
      state.clearSessionLocalState(sid)
      await refreshSessions()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(sid, msg)
    }
  }, [])
}

export function useSendPrompt() {
  const provider = useSettingsStore((s) => s.selectedProvider)
  const model = useSettingsStore((s) => s.selectedModel)
  const activeProjectId = useSettingsStore((s) => s.activeProjectId)
  const permissionMode = useSettingsStore((s) => s.permissionMode)
  const autoCompactEnabled = useSettingsStore((s) => s.autoCompactEnabled)
  const autoCompactThreshold = useSettingsStore((s) => s.autoCompactThreshold)
  const locale = useSettingsStore((s) => s.locale)
  const summaryProvider = useSettingsStore((s) => s.compactSummaryProvider)
  const summaryModel = useSettingsStore((s) => s.compactSummaryModel)
  const maxConcurrent = useSettingsStore((s) => s.maxConcurrentSessions)
  return useCallback(async (text: string, attachments?: Attachment[]) => {
    const store = useAgentStore.getState()
    let sid = store.sessionId
    // 並發上限 — 同時 in-flight 不超過 maxConcurrentSessions(Phase 31-M)
    // 同一 session 的 re-send(continue)不算新並發,所以只在「新開一條」時擋
    const runningCount = Object.values(store.busyBySession).filter(Boolean).length
    const isContinuingExisting = sid && store.busyBySession[sid]
    if (!isContinuingExisting && runningCount >= maxConcurrent) {
      const errSid = sid ?? '__global__'
      useAgentStore.getState().setError(
        errSid,
        `已達同時對話上限(${maxConcurrent})— 等其中一個跑完,或到 Settings 調高`,
      )
      return
    }
    if (!sid) {
      // Lazy create — 首次 send 才建 DB session,讓空 New chat 不污染 sidebar
      try {
        sid = await createConversation(provider, model, {
          projectId: activeProjectId,
        })
        useAgentStore.getState().setSessionId(sid)
        // 帶入 Settings 的 default budget cap(0 = 不限就跳過)
        const defaultBudget = useSettingsStore.getState().defaultBudgetUsd
        if (defaultBudget > 0) {
          const { setSessionBudget } = await import('../api/agent')
          await setSessionBudget(sid, defaultBudget).catch(() => {})
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        useAgentStore.getState().setError('__global__', msg)
        return
      }
    }
    // Capture sid in closure — 事件回來時 user 可能已切去別 session,
    // 但 sid 不變,events 仍寫進對應的 messagesBySession[sid]
    const targetSid: string = sid

    store.appendUserMessage(
      targetSid,
      text,
      (attachments ?? []).map((a) => ({
        previewUrl: a.preview_url || `data:${a.media_type};base64,${a.data}`,
        filename: a.filename || 'image',
        media_type: a.media_type,
      })),
    )
    const assistantId = store.beginAssistantMessage(targetSid)
    store.setError(targetSid, null)
    store.setBusy(targetSid, true)

    try {
      await rpcSendPrompt(
        targetSid,
        text,
        (ev: SidecarEvent) => applyEvent(targetSid, assistantId, ev),
        attachments,
        permissionMode,
        {
          autoCompactEnabled,
          autoCompactThreshold,
          locale,
          summaryProvider,
          summaryModel,
        },
      )
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(targetSid, msg)
    } finally {
      const state = useAgentStore.getState()
      state.endAssistantMessage(targetSid, assistantId)
      state.setBusy(targetSid, false)
      // 本 turn 結束(自然 / abort / error)— 若還有屬於這 assistantId 的
      // pendingQuestion(例如 user abort 時 banner 卡住),清掉避免殘留。
      const pq = state.pendingQuestionBySession[targetSid]
      if (pq && pq.assistantId === assistantId) {
        state.setPendingQuestion(targetSid, null)
      }
      refreshSessions()
      // 補新訊息的 messageIndex,讓 edit / delete 立刻可用,不必等切換對話
      void backfillMessageIndices(targetSid)
    }
  }, [provider, model, activeProjectId, permissionMode, autoCompactEnabled, autoCompactThreshold, locale, summaryProvider, summaryModel, maxConcurrent])
}

export function useAbort() {
  return useCallback(async () => {
    const sid = useAgentStore.getState().sessionId
    if (!sid) return
    try {
      await rpcAbort(sid)
    } catch {
      // 忽略 abort 自身的錯誤
    }
  }, [])
}

function applyEvent(sid: string, assistantId: string, ev: SidecarEvent) {
  const s = useAgentStore.getState()
  switch (ev.event) {
    case 'text_delta': {
      const data = ev.data as { text: string }
      s.appendAssistantText(sid, assistantId, data.text)
      break
    }
    case 'thinking_delta': {
      // 暫不渲染 thinking(可加 dimmer 區塊)
      break
    }
    case 'tool_start': {
      const data = ev.data as {
        tool_name: string
        tool_use_id: string
        input?: Record<string, unknown>
      }
      const message = (useAgentStore.getState().messagesBySession[sid] ?? []).find(
        (m) => m.id === assistantId,
      )
      const existing = message?.toolCalls?.find((t) => t.toolUseId === data.tool_use_id)
      if (!existing) {
        s.beginToolCall(sid, assistantId, {
          toolUseId: data.tool_use_id,
          toolName: data.tool_name,
          input: data.input,
        })
      }
      break
    }
    case 'ask_user_question': {
      const data = ev.data as {
        request_id: string
        questions: import('../api/agent').AskQuestion[]
      }
      s.setPendingQuestion(sid, {
        requestId: data.request_id,
        assistantId,
        questions: data.questions,
      })
      break
    }
    case 'tool_approval_request': {
      const data = ev.data as {
        tool_use_id: string
        tool_name: string
        input?: Record<string, unknown>
      }
      const message = (useAgentStore.getState().messagesBySession[sid] ?? []).find(
        (m) => m.id === assistantId,
      )
      const existing = message?.toolCalls?.find((t) => t.toolUseId === data.tool_use_id)
      if (!existing) {
        s.beginToolCall(sid, assistantId, {
          toolUseId: data.tool_use_id,
          toolName: data.tool_name,
          input: data.input,
        })
      }
      s.markToolAwaitingApproval(sid, data.tool_use_id)
      break
    }
    case 'tool_progress': {
      const data = ev.data as {
        tool_name: string
        tool_use_id: string
        progress: unknown
      }
      const message = (useAgentStore.getState().messagesBySession[sid] ?? []).find(
        (m) => m.id === assistantId,
      )
      const existing = message?.toolCalls?.find((t) => t.toolUseId === data.tool_use_id)
      if (!existing) {
        s.beginToolCall(sid, assistantId, {
          toolUseId: data.tool_use_id,
          toolName: data.tool_name,
        })
      }
      s.appendToolProgress(
        sid,
        data.tool_use_id,
        typeof data.progress === 'string'
          ? data.progress
          : JSON.stringify(data.progress),
      )
      break
    }
    case 'tool_error': {
      const data = ev.data as { tool_use_id: string; message: string }
      s.endToolCall(sid, data.tool_use_id, { isError: true, text: data.message })
      break
    }
    case 'tool_result': {
      const data = ev.data as {
        tool_name: string
        tool_use_id: string
        is_error: boolean
        text: string
      }
      const message = (useAgentStore.getState().messagesBySession[sid] ?? []).find(
        (m) => m.id === assistantId,
      )
      const existing = message?.toolCalls?.find((t) => t.toolUseId === data.tool_use_id)
      if (!existing) {
        s.beginToolCall(sid, assistantId, {
          toolUseId: data.tool_use_id,
          toolName: data.tool_name,
        })
      }
      s.endToolCall(sid, data.tool_use_id, {
        isError: data.is_error,
        text: data.text,
      })
      break
    }
    case 'turn_complete': {
      break
    }
    case 'loop_terminated': {
      const data = ev.data as { reason: string; total_turns: number }
      s.finishLoop(sid, { reason: data.reason, turns: data.total_turns })
      break
    }
    case 'compact_started': {
      s.setCompacting(sid, true)
      break
    }
    case 'compact_complete': {
      const data = ev.data as {
        summary: string
        before_tokens: number
        skipped?: boolean
        auto?: boolean
      }
      if (data.skipped) {
        s.setCompacting(sid, false)
      } else {
        const tail = data.auto ? 2 : 0
        s.applyCompactComplete(sid, data.summary, data.before_tokens, tail)
      }
      break
    }
  }
}

/** 從 DB 重新載入當前 session 的訊息(delete 後 / 編輯後同步 UI 用)。 */
async function reloadCurrentMessages(sid: string): Promise<void> {
  try {
    const loaded = await loadMessages(sid)
    _hydrateMessages(sid, loaded)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    useAgentStore.getState().setError(sid, msg)
  }
}

/** Turn 結束後給 streaming-new 訊息補 messageIndex / compacted / kind。
 *
 *  跟 reloadCurrentMessages 不同 — 不重建整個 messages 陣列(避免訊息物件
 *  identity 改變,造成 React 重 mount + 圖片 lazy reload 閃爍)。只 patch
 *  缺欄位,讓 streaming 出來的 user / assistant 也能取得 DB row index,
 *  之後 edit / delete 按鈕就會出現。
 *
 *  Positional merge:第 i 筆 current ↔ 第 i 筆 loaded。長度不齊就略過尾段。 */
async function backfillMessageIndices(sid: string): Promise<void> {
  try {
    const loaded = await loadMessages(sid)
    const current = useAgentStore.getState().messagesBySession[sid] ?? []
    const updated = current.map((m, i) => {
      const l = loaded[i]
      if (!l) return m
      if (
        typeof m.messageIndex === 'number' &&
        m.compacted === (l.compacted || undefined) &&
        m.kind === l.kind
      ) {
        return m
      }
      return {
        ...m,
        messageIndex: typeof m.messageIndex === 'number' ? m.messageIndex : l.message_index,
        compacted: m.compacted ?? l.compacted ?? undefined,
        kind: m.kind ?? l.kind,
      }
    })
    useAgentStore.getState().hydrateMessages(sid, updated)
  } catch {
    // 失敗略過 — 下次 reload 還有機會;不擋 UI
  }
}

/** 刪除指定 messageIndex(含)以後的對話。Cache 影響:被刪 prefix 後段 cache 失效。 */
export function useDeleteFrom() {
  return useCallback(async (messageIndex: number) => {
    const store = useAgentStore.getState()
    const sid = store.sessionId
    if (!sid) return
    if (store.busyBySession[sid] || store.compactingBySession[sid]) return
    // Optimistic UI:先把該 message 含以後砍掉
    const msgs = store.messagesBySession[sid] ?? []
    const cut = msgs.findIndex((m) => m.messageIndex === messageIndex)
    if (cut >= 0) {
      store.truncateMessages(sid, cut)
    }
    try {
      await rpcTruncate(sid, messageIndex, () => {
        /* 純 delete 不需要 streaming events */
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(sid, msg)
    }
    // Reload 對齊 DB 真實狀態 + 補上其他訊息的 messageIndex
    await reloadCurrentMessages(sid)
    refreshSessions()
  }, [])
}

/** 從指定 messageIndex(inclusive)分叉出新 session — 原 session 完全不動。
 *  Phase 31-R。新 session 自動切過去顯示;sidebar refresh 看得到。
 *
 *  Auto-continue:fork 點若停在 user 訊息 → AI 還沒回應 → 自動觸發 truncate
 *  + resend 同樣文字,新 session 拿到 AI 回應。原 session 完全不動。 */
export function useFork() {
  return useCallback(async (messageIndex: number, title?: string) => {
    const store = useAgentStore.getState()
    const sid = store.sessionId
    if (!sid) return null
    try {
      const { forkConversation } = await import('../api/agent')
      const newSid = await forkConversation(sid, messageIndex, title)
      // 切到新 session + load messages 進 store(sidebar 點選同一條路徑)
      useAgentStore.getState().switchToSession(newSid)
      const loaded = await loadMessages(newSid)
      _hydrateMessages(newSid, loaded)
      refreshSessions()

      // Auto-continue 若 fork 點是 user 訊息
      const last = loaded[loaded.length - 1]
      if (last && last.role === 'user' && last.text) {
        const lastText = last.text
        const assistantId = useAgentStore.getState().beginAssistantMessage(newSid)
        useAgentStore.getState().setBusy(newSid, true)
        try {
          await rpcTruncate(
            newSid,
            messageIndex,
            (ev: SidecarEvent) => applyEvent(newSid, assistantId, ev),
            {
              resendText: lastText,
              permissionMode: useSettingsStore.getState().permissionMode,
              locale: useSettingsStore.getState().locale,
            },
          )
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e)
          useAgentStore.getState().setError(newSid, msg)
        } finally {
          const st = useAgentStore.getState()
          st.endAssistantMessage(newSid, assistantId)
          st.setBusy(newSid, false)
          refreshSessions()
          void backfillMessageIndices(newSid)
        }
      }
      return newSid
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(sid, `Fork 失敗:${msg}`)
      return null
    }
  }, [])
}

/** 編輯 user 訊息並重送 — truncate + resend。前段保留,後段重新生成。 */
export function useEditAndResend() {
  const permissionMode = useSettingsStore((s) => s.permissionMode)
  const locale = useSettingsStore((s) => s.locale)
  return useCallback(
    async (messageIndex: number, newText: string, attachments?: Attachment[]) => {
      const store = useAgentStore.getState()
      const sid = store.sessionId
      if (!sid) return
      if (store.busyBySession[sid] || store.compactingBySession[sid]) return
      // Optimistic UI:砍舊 → push 新 user msg + assistant skeleton
      const msgs = store.messagesBySession[sid] ?? []
      const cut = msgs.findIndex((m) => m.messageIndex === messageIndex)
      if (cut >= 0) store.truncateMessages(sid, cut)
      store.appendUserMessage(
        sid,
        newText,
        (attachments ?? []).map((a) => ({
          previewUrl: a.preview_url || `data:${a.media_type};base64,${a.data}`,
          filename: a.filename || 'image',
          media_type: a.media_type,
        })),
      )
      const assistantId = store.beginAssistantMessage(sid)
      store.setError(sid, null)
      store.setBusy(sid, true)
      try {
        await rpcTruncate(
          sid,
          messageIndex,
          (ev: SidecarEvent) => applyEvent(sid, assistantId, ev),
          {
            resendText: newText,
            resendImages: attachments,
            permissionMode,
            locale,
          },
        )
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        useAgentStore.getState().setError(sid, msg)
      } finally {
        const st = useAgentStore.getState()
        st.endAssistantMessage(sid, assistantId)
        st.setBusy(sid, false)
        refreshSessions()
        if (sid) void backfillMessageIndices(sid)
      }
    },
    [permissionMode, locale],
  )
}

/** /compact 攔截 — InputBox 偵測到輸入文字是 /compact 時呼叫。
 *  不送 prompt,直接觸發 sidecar 的 conversation.compact RPC。 */
export function useCompactConversation() {
  const locale = useSettingsStore((s) => s.locale)
  const summaryProvider = useSettingsStore((s) => s.compactSummaryProvider)
  const summaryModel = useSettingsStore((s) => s.compactSummaryModel)
  return useCallback(async () => {
    const store = useAgentStore.getState()
    const sid = store.sessionId
    if (!sid) return
    if (store.busyBySession[sid] || store.compactingBySession[sid]) return
    store.setCompacting(sid, true)
    store.setError(sid, null)
    try {
      await rpcCompact(
        sid,
        (ev: SidecarEvent) => {
          // 用 dummy assistantId — compact 不會 emit text_delta / tool 事件
          applyEvent(sid, 'compact-rpc', ev)
        },
        { locale, summaryProvider, summaryModel },
      )
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(sid, msg)
      useAgentStore.getState().setCompacting(sid, false)
    } finally {
      // 萬一 sidecar 沒推 compact_complete(stale session 等)— 兜底清 flag
      const st = useAgentStore.getState()
      if (st.compactingBySession[sid]) st.setCompacting(sid, false)
    }
  }, [locale, summaryProvider, summaryModel])
}
