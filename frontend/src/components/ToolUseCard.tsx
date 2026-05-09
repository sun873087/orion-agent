import { useState } from 'react'

interface Props {
  toolName: string
  input: Record<string, unknown>
}

export function ToolUseCard({ toolName, input }: Props) {
  const [open, setOpen] = useState(false)
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
          className="shrink-0 text-claude-orange"
        >
          <path
            d="M3.5 5l3.5 3.5L11 5M3.5 9l3.5 3.5L11 9"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="font-medium text-claude-text">{toolName}</span>
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
        <pre className="mx-3 mb-3 px-3 py-2 rounded-md bg-claude-code text-claude-codeText text-[12px] overflow-x-auto whitespace-pre-wrap break-all border border-claude-borderSoft">
          {JSON.stringify(input, null, 2)}
        </pre>
      )}
    </div>
  )
}
