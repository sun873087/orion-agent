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
 * "New chat" 按鈕。只清空 local state,不立即建 DB session。首次 send 時
 * useSendPrompt 偵測 sessionId==null 才呼叫 createConversation。
 */
export function useNewConversation() {
  return useCallback(() => {
    useAgentStore.setState({
      sessionId: null,
      messages: [],
      error: null,
      lastLoopStatus: null,
    })
  }, [])
}

export function useSwitchConversation() {
  return useCallback(async (sid: string) => {
    const store = useAgentStore.getState()
    store.switchToSession(sid)
    try {
      const loaded = await loadMessages(sid)
      _hydrateMessages(sid, loaded)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(`failed to load history: ${msg}`)
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
    createdAt: Date.now(),
  }))
  useAgentStore.setState({ messages })
}

export function useRegenerate() {
  return useCallback(async () => {
    const store = useAgentStore.getState()
    const sid = store.sessionId
    if (!sid || store.busy) return

    // Drop last assistant message (UI) — sidecar 同時 truncate DB + state
    const msgs = store.messages
    let lastUserIdx = -1
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'user') {
        lastUserIdx = i
        break
      }
    }
    if (lastUserIdx < 0) return
    useAgentStore.setState({ messages: msgs.slice(0, lastUserIdx + 1) })

    const assistantId = store.beginAssistantMessage()
    store.setError(null)
    store.setBusy(true)
    try {
      await regenerateLast(sid, (ev: SidecarEvent) => applyEvent(assistantId, ev))
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(msg)
    } finally {
      useAgentStore.getState().endAssistantMessage(assistantId)
      useAgentStore.getState().setBusy(false)
      refreshSessions()
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
        state.switchToSession('')
        useAgentStore.setState({ sessionId: null })
      }
      await refreshSessions()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(msg)
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
  return useCallback(async (text: string, attachments?: Attachment[]) => {
    const store = useAgentStore.getState()
    let sid = store.sessionId
    if (!sid) {
      // Lazy create — 首次 send 才建 DB session,讓空 New chat 不污染 sidebar
      try {
        sid = await createConversation(provider, model, {
          projectId: activeProjectId,
        })
        useAgentStore.getState().setSessionId(sid)
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        useAgentStore.getState().setError(msg)
        return
      }
    }

    store.appendUserMessage(
      text,
      (attachments ?? []).map((a) => ({
        previewUrl: a.preview_url || `data:${a.media_type};base64,${a.data}`,
        filename: a.filename || 'image',
        media_type: a.media_type,
      })),
    )
    const assistantId = store.beginAssistantMessage()
    store.setError(null)
    store.setBusy(true)

    try {
      await rpcSendPrompt(
        sid,
        text,
        (ev: SidecarEvent) => applyEvent(assistantId, ev),
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
      useAgentStore.getState().setError(msg)
    } finally {
      const state = useAgentStore.getState()
      state.endAssistantMessage(assistantId)
      state.setBusy(false)
      // 本 turn 結束(自然 / abort / error)— 若還有屬於這 assistantId 的
      // pendingQuestion(例如 user abort 時 banner 卡住),清掉避免殘留。
      const pq = state.pendingQuestion
      if (pq && pq.assistantId === assistantId) {
        state.setPendingQuestion(null)
      }
      refreshSessions()
    }
  }, [provider, model, activeProjectId, permissionMode, autoCompactEnabled, autoCompactThreshold, locale, summaryProvider, summaryModel])
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

function applyEvent(assistantId: string, ev: SidecarEvent) {
  const s = useAgentStore.getState()
  switch (ev.event) {
    case 'text_delta': {
      const data = ev.data as { text: string }
      s.appendAssistantText(assistantId, data.text)
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
      const message = useAgentStore.getState().messages.find((m) => m.id === assistantId)
      const existing = message?.toolCalls?.find((t) => t.toolUseId === data.tool_use_id)
      if (!existing) {
        s.beginToolCall(assistantId, {
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
      s.setPendingQuestion({
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
      // tool_start 一定先到,所以 toolCall 已存在;改 status 等 user 決定
      const message = useAgentStore.getState().messages.find((m) => m.id === assistantId)
      const existing = message?.toolCalls?.find((t) => t.toolUseId === data.tool_use_id)
      if (!existing) {
        s.beginToolCall(assistantId, {
          toolUseId: data.tool_use_id,
          toolName: data.tool_name,
          input: data.input,
        })
      }
      s.markToolAwaitingApproval(data.tool_use_id)
      break
    }
    case 'tool_progress': {
      const data = ev.data as {
        tool_name: string
        tool_use_id: string
        progress: unknown
      }
      // 若該 tool 尚未在 message 上,start it now
      const message = useAgentStore.getState().messages.find((m) => m.id === assistantId)
      const existing = message?.toolCalls?.find((t) => t.toolUseId === data.tool_use_id)
      if (!existing) {
        s.beginToolCall(assistantId, {
          toolUseId: data.tool_use_id,
          toolName: data.tool_name,
        })
      }
      s.appendToolProgress(
        data.tool_use_id,
        typeof data.progress === 'string'
          ? data.progress
          : JSON.stringify(data.progress),
      )
      break
    }
    case 'tool_error': {
      const data = ev.data as { tool_use_id: string; message: string }
      s.endToolCall(data.tool_use_id, { isError: true, text: data.message })
      break
    }
    case 'tool_result': {
      const data = ev.data as {
        tool_name: string
        tool_use_id: string
        is_error: boolean
        text: string
      }
      const message = useAgentStore.getState().messages.find((m) => m.id === assistantId)
      const existing = message?.toolCalls?.find((t) => t.toolUseId === data.tool_use_id)
      if (!existing) {
        s.beginToolCall(assistantId, {
          toolUseId: data.tool_use_id,
          toolName: data.tool_name,
        })
      }
      s.endToolCall(data.tool_use_id, {
        isError: data.is_error,
        text: data.text,
      })
      break
    }
    case 'turn_complete': {
      // streaming 還沒徹底結束(可能還有下一個 turn),但目前 assistant 訊息可結束
      break
    }
    case 'loop_terminated': {
      const data = ev.data as { reason: string; total_turns: number }
      s.finishLoop({ reason: data.reason, turns: data.total_turns })
      break
    }
    case 'compact_started': {
      s.setCompacting(true)
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
        s.setCompacting(false)
      } else {
        // Auto 路徑:剛 appendUserMessage + beginAssistantMessage,後 2 筆是
        //          這次 send 的 live tail,不該被標 compacted。
        // 手動 /compact:全部既存 messages 都進 compacted 區。
        const tail = data.auto ? 2 : 0
        s.applyCompactComplete(data.summary, data.before_tokens, tail)
      }
      break
    }
  }
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
    if (!sid || store.busy || store.compacting) return
    store.setCompacting(true)
    store.setError(null)
    try {
      await rpcCompact(
        sid,
        (ev: SidecarEvent) => {
          // 用 dummy assistantId — compact 不會 emit text_delta / tool 事件
          applyEvent('compact-rpc', ev)
        },
        { locale, summaryProvider, summaryModel },
      )
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(msg)
      useAgentStore.getState().setCompacting(false)
    } finally {
      // 萬一 sidecar 沒推 compact_complete(stale session 等)— 兜底清 flag
      const st = useAgentStore.getState()
      if (st.compacting) st.setCompacting(false)
    }
  }, [locale, summaryProvider, summaryModel])
}
