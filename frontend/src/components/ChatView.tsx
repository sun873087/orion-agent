import { useEffect, useMemo, useRef, useState } from 'react'
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
import { WorkspaceFiles } from './WorkspaceFiles'

interface Props {
  sessionId: string | null
  token: string | null
  currentSession: SessionSummary | null
  catalog: ModelCatalog | null
  /** Draft mode: 使用者按 New chat 但還沒送訊息;sessionId 會是 null。 */
  draft: ModelChoice | null
  /** Draft mode 送第一則訊息時呼叫,實際建立 session 並回傳 sid。 */
  onCommitDraft: () => Promise<string | null>
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
      const entries = flushLive(
        state.entries,
        state.liveAssistant,
        state.liveThinking,
      )
      entries.push({ kind: 'user', id: newId(), text: ev.text })
      return { ...state, entries, liveAssistant: '', liveThinking: '' }
    }
    case 'history_replay_done':
      return {
        ...state,
        entries: flushLive(
          state.entries,
          state.liveAssistant,
          state.liveThinking,
        ),
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
      // flushLive 先把累積的 assistant/thinking 文字推 entry —
      // 這樣下面 last entry 不會是 tool_group(被文字隔開)→ 自動切新 group。
      const entries = flushLive(
        state.entries,
        state.liveAssistant,
        state.liveThinking,
      )
      const last = entries[entries.length - 1]
      const newItem = {
        toolUseId: ev.tool_use_id,
        toolName: ev.tool_name,
        input: ev.input,
      }
      if (last && last.kind === 'tool_group') {
        // append 進現有 group(同 group 規則:assistant 文字未介入)
        entries[entries.length - 1] = {
          ...last,
          items: [...last.items, newItem],
        }
      } else {
        entries.push({
          kind: 'tool_group',
          id: newId(),
          items: [newItem],
        })
      }
      return { ...state, entries, liveAssistant: '', liveThinking: '' }
    }
    case 'tool_result': {
      // 倒序找最後一個 tool_group,在 items 內以 toolUseId match,fill result
      const entries = [...state.entries]
      for (let i = entries.length - 1; i >= 0; i--) {
        const e = entries[i]
        if (!e || e.kind !== 'tool_group') continue
        const items = e.items.map((it) =>
          it.toolUseId === ev.tool_use_id
            ? {
                ...it,
                result: { content: ev.content, isError: ev.is_error ?? false },
              }
            : it,
        )
        entries[i] = { ...e, items }
        break
      }
      return { ...state, entries }
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
  draft,
  onCommitDraft,
  onOpenSettings,
  onModelChange,
}: Props) {
  const ws = useWebSocket(sessionId, token)

  const [flow, setFlow] = useState<FlowState>(EMPTY)
  const processedCountRef = useRef(0)
  // draft → real session 之間的 pending message。sessionId 變動時 flow 會被
  // 重置成 EMPTY,所以這個訊息只能存在 ref 裡才不會被洗掉。WS open 後 flush。
  const pendingDraftSendRef = useRef<string | null>(null)

  useEffect(() => {
    setFlow(EMPTY)
    processedCountRef.current = 0
  }, [sessionId])

  // draft 模式下 commit 完 sid,等 WS open 後把訊息送出
  useEffect(() => {
    if (sessionId && ws.status === 'open' && pendingDraftSendRef.current) {
      const text = pendingDraftSendRef.current
      pendingDraftSendRef.current = null
      setFlow((s) => ({
        ...s,
        entries: [...s.entries, { kind: 'user', id: newId(), text }],
        inFlight: true,
      }))
      ws.send({ type: 'user_message', content: text })
    }
  }, [sessionId, ws.status, ws])

  // server 在 reconnect 會 replay history → useWebSocket reset events 為 [],
  // 我們也得把處理過的 cursor 同步歸零,否則新 events 會被當成「已處理」跳過。
  useEffect(() => {
    if (ws.events.length < processedCountRef.current) {
      processedCountRef.current = 0
      setFlow(EMPTY)
    }
  }, [ws.events])

  useEffect(() => {
    const start = processedCountRef.current
    if (ws.events.length <= start) return
    setFlow((prev) => {
      let next = prev
      for (let i = start; i < ws.events.length; i++) {
        next = reduce(next, ws.events[i]!)
      }
      return next
    })
    processedCountRef.current = ws.events.length
  }, [ws.events])

  // reconnect banner: reconnecting 超過 1s 才顯示,避免短暫抖動 flicker
  const [showReconnectBanner, setShowReconnectBanner] = useState(false)
  useEffect(() => {
    if (ws.status !== 'reconnecting') {
      setShowReconnectBanner(false)
      return
    }
    const t = setTimeout(() => setShowReconnectBanner(true), 1_000)
    return () => clearTimeout(t)
  }, [ws.status])

  function send(text: string, attachments: UploadSummary[]) {
    let combined = text
    if (attachments.length > 0) {
      const refs = attachments
        .map((a) => `[Attached: ${a.filename} (upload_id=${a.upload_id})]`)
        .join('\n')
      combined = combined ? `${combined}\n\n${refs}` : refs
    }
    if (!combined) return
    if (!sessionId) {
      // draft 模式:先建 session,WS open 後才實際發訊息
      if (!draft) return
      pendingDraftSendRef.current = combined
      void onCommitDraft().then((sid) => {
        if (!sid) pendingDraftSendRef.current = null
      })
      return
    }
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
              ws.status === 'open'
                ? 'bg-emerald-500'
                : ws.status === 'connecting' || ws.status === 'reconnecting'
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-claude-textFaint'
            }`}
            title={ws.status}
          />
          <span className="font-mono text-claude-textDim">
            {sessionId
              ? `${sessionId.slice(0, 8)}…`
              : draft
                ? 'new chat'
                : 'no session'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <ModelBadge
            provider={currentSession?.provider}
            model={currentSession?.model}
            catalog={catalog}
          />
          <WorkspaceFiles sessionId={sessionId} refreshKey={turnCount} />
          <CostBadge sessionId={sessionId} refreshKey={turnCount} />
          <button
            onClick={onOpenSettings}
            className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-panel hover:text-claude-text transition-colors"
            title="Settings"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>
      </header>

      {showReconnectBanner && (
        <div className="px-5 py-2 text-[12px] text-amber-800 bg-amber-50 border-y border-amber-200 dark:text-amber-200 dark:bg-amber-950/40 dark:border-amber-900/50 flex items-center gap-2">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
          Reconnecting to server…
        </div>
      )}

      {(isEmpty && sessionId) || (!sessionId && draft) ? (
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
          {(currentSession || draft) && (
            <ModelPicker
              value={
                currentSession
                  ? {
                      provider: currentSession.provider,
                      model: currentSession.model,
                    }
                  : draft!
              }
              catalog={catalog}
              onChange={onModelChange}
            />
          )}
        </div>
      ) : (
        <MessageList
          key={sessionId ?? 'none'}
          entries={flow.entries}
          pendingPermissions={ws.pendingPermissions}
          liveAssistant={flow.liveAssistant}
          liveThinking={flow.liveThinking}
          onPermissionDecide={ws.answerPermission}
        />
      )}

      <InputBox
        // 連線抖動時(connecting / reconnecting)仍允許打字 — useWebSocket 會把
        // send queue 起來,open 時 flush。只有真的 closed (token 失效 / 重試耗盡)
        // 或已知 inFlight 才 disable。draft 模式無 sessionId 但允許輸入。
        disabled={
          (!sessionId && !draft) || ws.status === 'closed' || flow.inFlight
        }
        onSend={send}
        onAbort={ws.abort}
      />
    </main>
  )
}
