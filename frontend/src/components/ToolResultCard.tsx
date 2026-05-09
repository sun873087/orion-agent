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
  const accent = isError ? 'text-red-600' : 'text-claude-textDim'
  return (
    <div className="rounded-lg border border-claude-border bg-claude-cream/50 text-[13px]">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-claude-borderSoft/40 transition-colors rounded-lg"
        onClick={() => setOpen((v) => !v)}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          className={`shrink-0 ${accent}`}
        >
          {isError ? (
            <>
              <circle
                cx="8"
                cy="8"
                r="6"
                stroke="currentColor"
                strokeWidth="1.5"
              />
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
        <span className={`font-medium ${isError ? 'text-red-700' : 'text-claude-text'}`}>
          {isError ? 'Error from ' : ''}
          {toolName}
        </span>
        <span className="ml-auto text-claude-textFaint">
          <svg
            width="12"
            height="12"
            viewBox="0 0 16 16"
            fill="none"
            className={`transition-transform ${open ? 'rotate-180' : ''}`}
          >
            <path
              d="M4 6l4 4 4-4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </button>
      {open && (
        <div className="mx-3 mb-3 px-3 py-2 rounded-md bg-claude-code text-claude-codeText text-[12px] border border-claude-borderSoft">
          <pre className="overflow-x-auto whitespace-pre-wrap break-words max-h-96">
            {display}
          </pre>
          {truncated && open && (
            <div className="text-[11px] text-claude-textFaint mt-1.5">
              ({content.length} characters total)
            </div>
          )}
        </div>
      )}
    </div>
  )
}
