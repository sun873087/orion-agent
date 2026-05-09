import { useEffect, useMemo, useState } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import type {
  ModelCatalog,
  ServerEvent,
  SessionSummary,
  UploadSummary,
} from '../types/events'
import type { ModelChoice } from '../lib/preferredModel'
import { CostBadge } from './CostBadge'
import { type FlowEntry, MessageList } from './MessageList'
import { InputBox } from './InputBox'
import { ModelBadge } from './ModelBadge'
import { ModelPicker } from './ModelPicker'

interface Props {
  sessionId: string | null
  token: string | null
  currentSession: SessionSummary | null
  catalog: ModelCatalog | null
  onOpenSettings: () => void
  onModelChange: (choice: ModelChoice) => void
}

let _flowId = 0
const newId = () => `f${++_flowId}`

interface FlowState {
  entries: FlowEntry[]
  liveAssistant: string
  liveThinking: string
  inFlight: boolean
}

const EMPTY: FlowState = {
  entries: [],
  liveAssistant: '',
  liveThinking: '',
  inFlight: false,
}

function flushLive(
  entries: FlowEntry[],
  liveAssistant: string,
  liveThinking: string,
): FlowEntry[] {
  const out = [...entries]
  if (liveAssistant.trim()) {
    out.push({ kind: 'assistant', id: newId(), text: liveAssistant })
  }
  if (liveThinking.trim()) {
    out.push({ kind: 'thinking', id: newId(), text: liveThinking })
  }
  return out
}

function reduce(state: FlowState, ev: ServerEvent): FlowState {
  switch (ev.type) {
    case 'user_text': {
      // 重播時 server 送過去 user 訊息給 client 顯示
      const entries = flushLive(state.entries, state.liveAssistant, state.liveThinking)
      entries.push({ kind: 'user', id: newId(), text: ev.text })
      return { ...state, entries, liveAssistant: '', liveThinking: '' }
    }
    case 'history_replay_done':
      return {
        ...state,
        entries: flushLive(state.entries, state.liveAssistant, state.liveThinking),
        liveAssistant: '',
        liveThinking: '',
        // 重播不應該讓 inFlight 鎖住輸入
        inFlight: false,
      }
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

export function ChatView({
  sessionId,
  token,
  currentSession,
  catalog,
  onOpenSettings,
  onModelChange,
}: Props) {
  const ws = useWebSocket(sessionId, token)

  const [flow, setFlow] = useState<FlowState>(EMPTY)
  const [processedCount, setProcessedCount] = useState(0)

  useEffect(() => {
    setFlow(EMPTY)
    setProcessedCount(0)
  }, [sessionId])

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
        .map((a) => `[Attached: ${a.filename} (upload_id=${a.upload_id})]`)
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

  const isEmpty =
    flow.entries.length === 0 && !flow.liveAssistant && !flow.liveThinking

  return (
    <main className="flex-1 flex flex-col min-w-0 bg-claude-cream">
      <header className="flex items-center justify-between px-5 py-3 text-[13px]">
        <div className="flex items-center gap-2.5 text-claude-textDim">
          <span
            className={`inline-block h-2 w-2 rounded-full transition-colors ${
              ws.connected ? 'bg-emerald-500' : 'bg-claude-textFaint'
            }`}
            title={ws.connected ? 'connected' : 'disconnected'}
          />
          <span className="font-mono text-claude-textDim">
            {sessionId ? `${sessionId.slice(0, 8)}…` : 'no session'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <ModelBadge
            provider={currentSession?.provider}
            model={currentSession?.model}
            catalog={catalog}
          />
          <CostBadge sessionId={sessionId} refreshKey={turnCount} />
          <button
            onClick={onOpenSettings}
            className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-panel hover:text-claude-text transition-colors"
            title="Settings"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle
                cx="8"
                cy="8"
                r="2"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <path
                d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8L3.4 3.4"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </header>

      {isEmpty && sessionId ? (
        <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-claude-orange text-white text-lg font-semibold mb-4">
            O
          </div>
          <div className="text-[22px] font-medium text-claude-text mb-1">
            What can I help with today?
          </div>
          <div className="text-[14px] text-claude-textDim mb-5">
            Pick a model below, then type your first message.
          </div>
          {currentSession && (
            <ModelPicker
              value={{
                provider: currentSession.provider,
                model: currentSession.model,
              }}
              catalog={catalog}
              onChange={onModelChange}
            />
          )}
        </div>
      ) : (
        <MessageList
          entries={flow.entries}
          pendingPermissions={ws.pendingPermissions}
          liveAssistant={flow.liveAssistant}
          liveThinking={flow.liveThinking}
          onPermissionDecide={ws.answerPermission}
        />
      )}

      <InputBox
        disabled={!sessionId || !ws.connected || flow.inFlight}
        onSend={send}
        onAbort={ws.abort}
      />
    </main>
  )
}
