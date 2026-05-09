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
  /** 目前 streaming 中尚未 turn_complete 的 assistant text;非空時掛在最後。 */
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
      className="flex-1 overflow-y-auto p-4 space-y-2 bg-gray-50"
    >
      {entries.map((e) => {
        switch (e.kind) {
          case 'user':
            return <MessageBubble key={e.id} role="user" text={e.text} />
          case 'assistant':
            return <MessageBubble key={e.id} role="assistant" text={e.text} />
          case 'thinking':
            return <MessageBubble key={e.id} role="thinking" text={e.text} />
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
                className="text-xs text-gray-400 text-right pr-2"
              >
                turn end · {e.stop_reason} · {e.input_tokens} in /{' '}
                {e.output_tokens} out
              </div>
            )
          case 'terminal':
            return (
              <div
                key={e.id}
                className="text-center text-gray-400 text-sm py-2 border-t border-gray-200"
              >
                ━━ {e.reason} ({e.total_turns} turns) ━━
              </div>
            )
          case 'error':
            return (
              <div
                key={e.id}
                className="bg-red-50 text-red-700 p-3 rounded border border-red-200"
              >
                ❌ {e.message}
              </div>
            )
        }
      })}

      {/* live thinking */}
      {liveThinking && <MessageBubble role="thinking" text={liveThinking} />}

      {/* live assistant streaming */}
      {liveAssistant && <MessageBubble role="assistant" text={liveAssistant} />}

      {/* pending permission dialogs */}
      {pendingPermissions.map((p) => (
        <PermissionDialog
          key={p.request_id}
          event={p}
          onDecide={(d) => onPermissionDecide(p.request_id, d)}
        />
      ))}

      {entries.length === 0 && !liveAssistant && !liveThinking && (
        <div className="text-center text-gray-400 text-sm pt-12">
          Start a conversation by typing below.
        </div>
      )}
    </div>
  )
}
