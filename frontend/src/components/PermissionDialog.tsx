import type { PermissionAskEvent } from '../types/events'

interface Props {
  event: PermissionAskEvent
  onDecide: (
    decision: 'allow' | 'always_allow' | 'deny' | 'always_deny',
  ) => void
}

export function PermissionDialog({ event, onDecide }: Props) {
  return (
    <div className="rounded-xl border border-claude-orange/40 bg-claude-orangeSoft/40 p-4 animate-fade-in">
      <div className="flex items-start gap-2.5 mb-3">
        <svg
          width="18"
          height="18"
          viewBox="0 0 18 18"
          fill="none"
          className="shrink-0 mt-0.5 text-claude-orange"
        >
          <rect
            x="3.5"
            y="7.5"
            width="11"
            height="8"
            rx="1.5"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <path
            d="M6 7.5V5a3 3 0 016 0v2.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
        <div>
          <div className="font-medium text-claude-text text-[14px]">
            Allow{' '}
            <code className="font-mono bg-white/60 px-1.5 py-0.5 rounded text-[13px]">
              {event.tool_name}
            </code>
            ?
          </div>
          <div className="text-[12px] text-claude-textDim mt-0.5">
            Orion is asking permission to use this tool.
          </div>
        </div>
      </div>

      <pre className="text-[12px] bg-white/70 border border-claude-orange/20 rounded-md px-3 py-2 mb-3 overflow-x-auto whitespace-pre-wrap break-words max-h-40">
        {JSON.stringify(event.input, null, 2)}
      </pre>

      <div className="flex flex-wrap gap-2">
        <button
          className="px-3.5 py-1.5 bg-claude-orange text-white rounded-md hover:bg-claude-orangeHover text-[13px] font-medium transition-colors"
          onClick={() => onDecide('allow')}
        >
          Allow once
        </button>
        <button
          className="px-3.5 py-1.5 bg-white border border-claude-border text-claude-text rounded-md hover:bg-claude-borderSoft text-[13px] font-medium transition-colors"
          onClick={() => onDecide('always_allow')}
        >
          Always allow
        </button>
        <button
          className="px-3.5 py-1.5 bg-white border border-claude-border text-claude-textDim rounded-md hover:bg-claude-borderSoft hover:text-claude-text text-[13px] transition-colors"
          onClick={() => onDecide('deny')}
        >
          Deny
        </button>
        <button
          className="px-3.5 py-1.5 bg-white border border-claude-border text-claude-textDim rounded-md hover:bg-red-50 hover:border-red-200 hover:text-red-700 text-[13px] transition-colors"
          onClick={() => onDecide('always_deny')}
        >
          Always deny
        </button>
      </div>
      {event.timeout_seconds && (
        <div className="text-[11px] text-claude-textFaint mt-2">
          Timeout: {event.timeout_seconds}s
        </div>
      )}
    </div>
  )
}
