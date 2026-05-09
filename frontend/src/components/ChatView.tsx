import { useEffect, useMemo, useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import type { ServerEvent, UploadSummary } from '../types/events'
import { CostBadge } from './CostBadge'
import { type FlowEntry, MessageList } from './MessageList'
import { InputBox } from './InputBox'

interface Props {
  sessionId: string | null
  token: string | null
}

let _flowId = 0
const newId = () => `f${++_flowId}`

interface FlowState {
  entries: FlowEntry[]
  liveAssistant: string
  liveThinking: string
  /** 模型仍在 streaming(turn_complete 之前)— UI 鎖輸入框。 */
  inFlight: boolean
}

const EMPTY: FlowState = {
  entries: [],
  liveAssistant: '',
  liveThinking: '',
  inFlight: false,
}

/**
 * 把 server events 摺成 FlowEntry 列表;assistant_text 累積進 liveAssistant,
 * 在第一個 tool_use / turn_complete 時凝固成 entry。
 */
function reduce(state: FlowState, ev: ServerEvent): FlowState {
  switch (ev.type) {
    case 'assistant_text':
      return { ...state, liveAssistant: state.liveAssistant + ev.text }
    case 'assistant_thinking':
      return { ...state, liveThinking: state.liveThinking + ev.text }
    case 'tool_use': {
      const entries = [...state.entries]
      if (state.liveAssistant.trim()) {
        entries.push({
          kind: 'assistant',
          id: newId(),
          text: state.liveAssistant,
        })
      }
      if (state.liveThinking.trim()) {
        entries.push({
          kind: 'thinking',
          id: newId(),
          text: state.liveThinking,
        })
      }
      entries.push({
        kind: 'tool_use',
        id: newId(),
        tool_name: ev.tool_name,
        input: ev.input,
      })
      return { ...state, entries, liveAssistant: '', liveThinking: '' }
    }
    case 'tool_result':
      return {
        ...state,
        entries: [
          ...state.entries,
          {
            kind: 'tool_result',
            id: newId(),
            tool_name: ev.tool_name,
            content: ev.content,
            isError: ev.is_error ?? false,
          },
        ],
      }
    case 'turn_complete': {
      const entries = [...state.entries]
      if (state.liveAssistant.trim()) {
        entries.push({
          kind: 'assistant',
          id: newId(),
          text: state.liveAssistant,
        })
      }
      if (state.liveThinking.trim()) {
        entries.push({
          kind: 'thinking',
          id: newId(),
          text: state.liveThinking,
        })
      }
      entries.push({
        kind: 'turn_complete',
        id: newId(),
        stop_reason: ev.stop_reason,
        input_tokens: ev.input_tokens,
        output_tokens: ev.output_tokens,
      })
      return {
        ...state,
        entries,
        liveAssistant: '',
        liveThinking: '',
        // 還在 in-flight,直到 terminal 才釋放
      }
    }
    case 'terminal':
      return {
        ...state,
        entries: [
          ...state.entries,
          {
            kind: 'terminal',
            id: newId(),
            reason: ev.reason,
            total_turns: ev.total_turns,
          },
        ],
        inFlight: false,
      }
    case 'error':
      return {
        ...state,
        entries: [
          ...state.entries,
          { kind: 'error', id: newId(), message: ev.message },
        ],
        inFlight: false,
      }
    default:
      return state
  }
}

export function ChatView({ sessionId, token }: Props) {
  const ws = useWebSocket(sessionId, token)

  // events 是累積 list — 我們自己 reduce 成 FlowState
  const [flow, setFlow] = useState<FlowState>(EMPTY)
  const [processedCount, setProcessedCount] = useState(0)

  // 換 session 重置
  useEffect(() => {
    setFlow(EMPTY)
    setProcessedCount(0)
  }, [sessionId])

  // 增量 reduce events
  useEffect(() => {
    if (ws.events.length <= processedCount) return
    let next = flow
    for (let i = processedCount; i < ws.events.length; i++) {
      next = reduce(next, ws.events[i]!)
    }
    setFlow(next)
    setProcessedCount(ws.events.length)
  }, [ws.events, processedCount, flow])

  function send(text: string, attachments: UploadSummary[]) {
    if (!sessionId) return
    let combined = text
    if (attachments.length > 0) {
      const refs = attachments
        .map(
          (a) => `[Attached: ${a.filename} (upload_id=${a.upload_id})]`,
        )
        .join('\n')
      combined = combined ? `${combined}\n\n${refs}` : refs
    }
    if (!combined) return
    setFlow((s) => ({
      ...s,
      entries: [...s.entries, { kind: 'user', id: newId(), text: combined }],
      inFlight: true,
    }))
    ws.send({ type: 'user_message', content: combined })
  }

  const turnCount = useMemo(
    () => flow.entries.filter((e) => e.kind === 'turn_complete').length,
    [flow.entries],
  )

  return (
    <main className="flex-1 flex flex-col min-w-0">
      <header className="border-b border-gray-200 bg-white px-4 py-2 flex items-center justify-between text-sm">
        <div className="flex items-center gap-3">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              ws.connected ? 'bg-green-500' : 'bg-gray-400'
            }`}
            title={ws.connected ? 'connected' : 'disconnected'}
          />
          <span className="font-mono text-xs text-gray-700">
            {sessionId ? sessionId.slice(0, 8) + '…' : 'no session'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">turns: {turnCount}</span>
          <CostBadge sessionId={sessionId} refreshKey={turnCount} />
        </div>
      </header>

      <MessageList
        entries={flow.entries}
        pendingPermissions={ws.pendingPermissions}
        liveAssistant={flow.liveAssistant}
        liveThinking={flow.liveThinking}
        onPermissionDecide={ws.answerPermission}
      />

      <InputBox
        disabled={!sessionId || !ws.connected || flow.inFlight}
        onSend={send}
        onAbort={ws.abort}
      />
    </main>
  )
}
