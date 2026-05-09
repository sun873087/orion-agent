import { useEffect, useRef, useState } from 'react'
import type { PermissionAskEvent } from '../types/events'
import { MessageBubble } from './MessageBubble'
import { PermissionDialog } from './PermissionDialog'
import { ToolGroupCard } from './ToolGroupCard'
import type { ToolGroupItem } from '../lib/toolNarration'

export type FlowEntry =
  | { kind: 'user'; id: string; text: string }
  | { kind: 'assistant'; id: string; text: string }
  | { kind: 'thinking'; id: string; text: string }
  | { kind: 'tool_group'; id: string; items: ToolGroupItem[] }
  | {
      kind: 'turn_complete'
      id: string
      stop_reason: string
      input_tokens: number
      output_tokens: number
    }
  | { kind: 'terminal'; id: string; reason: string; total_turns: number }
  | { kind: 'error'; id: string; message: string }

interface Props {
  entries: FlowEntry[]
  pendingPermissions: PermissionAskEvent[]
  liveAssistant?: string
  liveThinking?: string
  onPermissionDecide: (
    requestId: string,
    decision: 'allow' | 'always_allow' | 'deny' | 'always_deny',
  ) => void
}

export function MessageList({
  entries,
  pendingPermissions,
  liveAssistant,
  liveThinking,
  onPermissionDecide,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  // sticky:user 已在底部 → 新訊息時自動 scroll;user 滾上去 → 不打擾
  const [sticky, setSticky] = useState(true)

  // user 手動滾動時更新 sticky:近底(< 80px)即重新黏底
  function onScroll() {
    const el = ref.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setSticky(distFromBottom < 80)
  }

  useEffect(() => {
    if (!sticky) return
    const el = ref.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [
    entries.length,
    liveAssistant,
    liveThinking,
    pendingPermissions.length,
    sticky,
  ])

  function jumpToBottom() {
    const el = ref.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    setSticky(true)
  }

  return (
    <div className="relative flex-1 min-h-0">
    <div
      ref={ref}
      onScroll={onScroll}
      className="absolute inset-0 overflow-y-auto"
    >
      <div className="max-w-3xl mx-auto px-6 py-6 space-y-3">
        {entries.map((e) => {
          switch (e.kind) {
            case 'user':
              return <MessageBubble key={e.id} role="user" text={e.text} />
            case 'assistant':
              return (
                <MessageBubble key={e.id} role="assistant" text={e.text} />
              )
            case 'thinking':
              return (
                <MessageBubble key={e.id} role="thinking" text={e.text} />
              )
            case 'tool_group':
              return <ToolGroupCard key={e.id} items={e.items} />
            case 'turn_complete':
              return (
                <div
                  key={e.id}
                  className="text-[11px] text-claude-textFaint pt-1"
                >
                  {e.input_tokens} in · {e.output_tokens} out · {e.stop_reason}
                </div>
              )
            case 'terminal':
              return (
                <div
                  key={e.id}
                  className="flex items-center gap-3 text-[11px] text-claude-textFaint py-2"
                >
                  <span className="flex-1 h-px bg-claude-border" />
                  <span>
                    {e.reason} · {e.total_turns} turns
                  </span>
                  <span className="flex-1 h-px bg-claude-border" />
                </div>
              )
            case 'error':
              return (
                <div
                  key={e.id}
                  className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-[13px]"
                >
                  {e.message}
                </div>
              )
          }
        })}

        {liveThinking && <MessageBubble role="thinking" text={liveThinking} />}
        {liveAssistant && (
          <MessageBubble role="assistant" text={liveAssistant} />
        )}

        {pendingPermissions.map((p) => (
          <PermissionDialog
            key={p.request_id}
            event={p}
            onDecide={(d) => onPermissionDecide(p.request_id, d)}
          />
        ))}
      </div>
    </div>
      {!sticky && (
        <button
          onClick={jumpToBottom}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white border border-claude-border shadow-md text-[12px] text-claude-textDim hover:text-claude-text hover:bg-claude-cream transition"
          title="Scroll to latest"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
            <path
              d="M4 6l4 4 4-4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Latest
        </button>
      )}
    </div>
  )
}
