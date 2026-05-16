import { useState } from 'react'
import { ChevronDown, ChevronRight, Loader2, CheckCircle2, XCircle } from 'lucide-react'

import type { ToolCallState } from '../store/agent'

const PREVIEW_LIMIT = 200

/** 摺疊式 tool call 區塊。Running 時看到 spinner + progress;完成顯示 result。 */
export function ToolCallPanel({ toolCall }: { toolCall: ToolCallState }) {
  // Running 時自動展開讓 user 看到即時 progress;結束後保留 user 手動的 open 狀態
  const isRunning = toolCall.status === 'running'
  const isError = toolCall.status === 'error'
  const [userToggled, setUserToggled] = useState<boolean | null>(null)
  const open = userToggled ?? isRunning

  const fullText = toolCall.text || toolCall.progress.join('\n')
  const preview =
    fullText.length > PREVIEW_LIMIT ? fullText.slice(0, PREVIEW_LIMIT) + '…' : fullText

  return (
    <div
      className={`overflow-hidden rounded-lg border ${
        isError ? 'border-error/30' : 'border-bg-hover'
      } bg-bg-panel`}
    >
      <button
        type="button"
        onClick={() => setUserToggled(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-bg-hover"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <StatusIcon status={toolCall.status} />
        <span className="font-mono text-xs text-fg-base">{toolCall.toolName}</span>
        {!isRunning && fullText && !open && (
          <span className="ml-2 truncate text-xs text-fg-muted">
            {preview.split('\n')[0]}
          </span>
        )}
      </button>
      {open && (
        <div className="border-t border-bg-hover bg-bg-input px-3 py-2">
          {isRunning && toolCall.progress.length === 0 ? (
            <div className="text-xs italic text-fg-muted">running…</div>
          ) : (
            <pre className="scrollbar-thin max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs text-fg-base">
              {fullText || '(no output)'}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function StatusIcon({ status }: { status: ToolCallState['status'] }) {
  if (status === 'running')
    return <Loader2 size={14} className="animate-spin text-fg-muted" />
  if (status === 'error') return <XCircle size={14} className="text-error" />
  return <CheckCircle2 size={14} className="text-success" />
}
