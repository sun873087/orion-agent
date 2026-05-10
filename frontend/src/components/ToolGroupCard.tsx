import { useState } from 'react'
import { ToolRow } from './ToolRow'
import { formatGroupSummary, type ToolGroupItem } from '../lib/toolNarration'

interface Props {
  items: ToolGroupItem[]
}

export function ToolGroupCard({ items }: Props) {
  const [open, setOpen] = useState(false)
  if (items.length === 0) return null

  const summary = formatGroupSummary(items)
  const inProgress = items.some((i) => i.result == null)
  const hasError = items.some((i) => i.result?.isError === true)

  return (
    <div className="text-[13px]">
      <button
        className="flex items-center gap-1.5 py-0.5 text-left text-claude-textDim hover:text-claude-text transition-colors group"
        onClick={() => setOpen((v) => !v)}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="none"
          className={`shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
        >
          <path
            d="M6 4l4 4-4 4"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span>{summary}</span>
        {inProgress && (
          <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-claude-orange animate-pulse" />
        )}
      </button>
      {open && (
        <div className="mt-1 ml-1 border-l-2 border-claude-borderSoft">
          {items.map((it) => (
            <ToolRow key={it.toolUseId} item={it} />
          ))}
          {!inProgress && (
            <div
              className={`pl-3 py-1 flex items-center gap-1.5 ${
                hasError
                  ? 'text-red-700 dark:text-red-300'
                  : 'text-emerald-700 dark:text-emerald-400'
              }`}
            >
              {hasError ? (
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
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
                </svg>
              ) : (
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M3 8l3.5 3.5L13 5"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
              <span>{hasError ? 'Error' : 'Done'}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
