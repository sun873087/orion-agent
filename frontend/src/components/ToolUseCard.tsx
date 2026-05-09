import { useState } from 'react'
import { ToolInputView, summarizeToolInput } from './ToolInputView'

interface Props {
  toolName: string
  input: Record<string, unknown>
}

export function ToolUseCard({ toolName, input }: Props) {
  const [open, setOpen] = useState(false)
  const summary = summarizeToolInput(toolName, input)

  return (
    <div className="text-[13px] border-l-2 border-claude-borderSoft pl-3">
      <button
        className="w-full flex items-center gap-2 py-1 text-left hover:text-claude-text transition-colors group"
        onClick={() => setOpen((v) => !v)}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="none"
          className={`shrink-0 text-claude-textFaint transition-transform ${
            open ? 'rotate-90' : ''
          }`}
        >
          <path
            d="M6 4l4 4-4 4"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="font-medium text-claude-textDim group-hover:text-claude-text">
          {toolName}
        </span>
        {summary && (
          <span className="font-mono text-[12px] px-1.5 py-0.5 rounded bg-claude-panel text-claude-textDim truncate max-w-[40ch]">
            {summary}
          </span>
        )}
      </button>
      {open && (
        <div className="mt-1.5 mb-2">
          <ToolInputView toolName={toolName} input={input} />
        </div>
      )}
    </div>
  )
}
