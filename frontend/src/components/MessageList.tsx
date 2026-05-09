import { useEffect, useRef } from 'react'
import type { PermissionAskEvent } from '../types/events'
import { MessageBubble } from './MessageBubble'
import { PermissionDialog } from './PermissionDialog'
import { ToolResultCard } from './ToolResultCard'
import { ToolUseCard } from './ToolUseCard'

export type FlowEntry =
  | { kind: 'user'; id: string; text: string }
  | { kind: 'assistant'; id: string; text: string }
  | { kind: 'thinking'; id: string; text: string }
  | {
      kind: 'tool_use'
      id: string
      tool_name: string
      input: Record<string, unknown>
    }
  | {
      kind: 'tool_result'
      id: string
      tool_name: string
      content: string
      isError: boolean
    }
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

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [entries.length, liveAssistant, liveThinking, pendingPermissions.length])

  return (
    <div
      ref={ref}
      className="flex-1 overflow-y-auto"
    >
      <div className="max-w-3xl mx-auto px-6 py-6 space-y-5">
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
            case 'tool_use':
              return (
                <ToolUseCard
                  key={e.id}
                  toolName={e.tool_name}
                  input={e.input}
                />
              )
            case 'tool_result':
              return (
                <ToolResultCard
                  key={e.id}
                  toolName={e.tool_name}
                  content={e.content}
                  isError={e.isError}
                />
              )
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
  )
}
