import { useState } from 'react'

interface Props {
  toolName: string
  content: string
  isError?: boolean
}

const TRUNCATE_LIMIT = 600

export function ToolResultCard({ toolName, content, isError }: Props) {
  const [open, setOpen] = useState(false)
  const truncated = content.length > TRUNCATE_LIMIT
  const display =
    !open && truncated ? content.slice(0, TRUNCATE_LIMIT) + '\n…' : content

  const label = isError ? `Error from ${toolName}` : 'Done'
  const labelClass = isError
    ? 'text-red-700'
    : 'text-claude-textDim group-hover:text-claude-text'

  return (
    <div className="text-[13px] border-l-2 border-claude-borderSoft pl-3">
      <button
        className="w-full flex items-center gap-2 py-1 text-left transition-colors group"
        onClick={() => setOpen((v) => !v)}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="none"
          className={`shrink-0 ${
            isError ? 'text-red-600' : 'text-emerald-600'
          }`}
        >
          {isError ? (
            <>
              <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
              <path
                d="M5.5 5.5l5 5M10.5 5.5l-5 5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </>
          ) : (
            <path
              d="M3 8l3.5 3.5L13 5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
        </svg>
        <span className={labelClass}>{label}</span>
        {content.length > 0 && (
          <span className="text-[11px] text-claude-textFaint">
            ({content.length} chars)
          </span>
        )}
      </button>
      {open && content.length > 0 && (
        <div className="mt-1.5 mb-2 px-2.5 py-1.5 rounded-md bg-claude-code text-claude-codeText text-[12px] border border-claude-borderSoft">
          <pre className="overflow-x-auto whitespace-pre-wrap break-words max-h-96">
            {display}
          </pre>
          {truncated && (
            <div className="text-[11px] text-claude-textFaint mt-1">
              ({content.length} characters total)
            </div>
          )}
        </div>
      )}
    </div>
  )
}
