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
  createConversation,
  sendPrompt as rpcSendPrompt,
  type SidecarEvent,
} from '../api/agent'
import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

export function useInitConversation() {
  const sessionId = useAgentStore((s) => s.sessionId)
  const setSessionId = useAgentStore((s) => s.setSessionId)
  const setInitError = useAgentStore((s) => s.setInitError)
  const provider = useSettingsStore((s) => s.selectedProvider)
  const model = useSettingsStore((s) => s.selectedModel)

  useEffect(() => {
    if (sessionId) return
    let cancelled = false
    createConversation(provider, model)
      .then((sid) => {
        if (!cancelled) setSessionId(sid)
      })
      .catch((e) => {
        if (!cancelled) setInitError(`failed to init conversation: ${String(e)}`)
      })
    return () => {
      cancelled = true
    }
  }, [sessionId, setSessionId, setInitError, provider, model])
}

export function useSendPrompt() {
  return useCallback(async (text: string) => {
    const store = useAgentStore.getState()
    const sid = store.sessionId
    if (!sid) return

    store.appendUserMessage(text)
    const assistantId = store.beginAssistantMessage()
    store.setError(null)
    store.setBusy(true)

    try {
      await rpcSendPrompt(sid, text, (ev: SidecarEvent) => {
        applyEvent(assistantId, ev)
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      useAgentStore.getState().setError(msg)
    } finally {
      useAgentStore.getState().endAssistantMessage(assistantId)
      useAgentStore.getState().setBusy(false)
    }
  }, [])
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
  }
}
