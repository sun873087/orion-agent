import { useState } from 'react'
import { ToolInputView } from './ToolInputView'
import {
  describeToolItem,
  toolTypeChip,
  type ToolGroupItem,
} from '../lib/toolNarration'

interface Props {
  item: ToolGroupItem
}

function ToolIcon({ toolName }: { toolName: string }) {
  // 用 emoji-style monochrome SVG（避免引 icon 套件）
  const cls = 'w-3.5 h-3.5 text-claude-textFaint shrink-0'
  switch (toolName) {
    case 'Bash':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={cls}>
          <path
            d="M3 5l3 3-3 3M8 11h5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'Read':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={cls}>
          <path
            d="M3 3.5h7l3 3v6a1 1 0 01-1 1H3a1 1 0 01-1-1V4.5a1 1 0 011-1z M10 3.5v3h3"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'Write':
    case 'Edit':
    case 'NotebookEdit':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={cls}>
          <path
            d="M3 13l1-3 7-7 2 2-7 7-3 1z"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'Glob':
    case 'Grep':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={cls}>
          <circle cx="7" cy="7" r="4" stroke="currentColor" strokeWidth="1.3" />
          <path
            d="M10 10l3 3"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
          />
        </svg>
      )
    case 'WebFetch':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={cls}>
          <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.3" />
          <path
            d="M2.5 8h11M8 2.5c2 2 2 9 0 11M8 2.5c-2 2-2 9 0 11"
            stroke="currentColor"
            strokeWidth="1.3"
          />
        </svg>
      )
    case 'Skill':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={cls}>
          <path
            d="M8 2l1.6 4.4 4.4.4-3.4 3 1 4.2L8 11.6 4.4 14l1-4.2-3.4-3 4.4-.4z"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
        </svg>
      )
    default:
      return (
        <svg viewBox="0 0 16 16" fill="none" className={cls}>
          <circle cx="8" cy="8" r="5" stroke="currentColor" strokeWidth="1.3" />
        </svg>
      )
  }
}

export function ToolRow({ item }: Props) {
  const [open, setOpen] = useState(false)
  const desc = describeToolItem(item)
  const chip = toolTypeChip(item.toolName)
  const inProgress = item.result == null
  const isError = item.result?.isError === true

  return (
    <div className="pl-3 py-0.5">
      <button
        className="w-full flex items-center gap-2 text-left text-claude-textDim hover:text-claude-text transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <ToolIcon toolName={item.toolName} />
        <span className={`truncate ${isError ? 'text-red-700' : ''}`}>
          {desc}
        </span>
        {inProgress && (
          <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-claude-orange animate-pulse" />
        )}
        <span className="ml-auto text-[11px] px-1.5 py-0.5 rounded bg-claude-panel text-claude-textFaint shrink-0">
          {chip}
        </span>
      </button>
      {open && (
        <div className="ml-5 mt-1 mb-2 space-y-1.5">
          <ToolInputView toolName={item.toolName} input={item.input} />
          {item.result && (
            <div className="text-[11px] text-claude-textFaint">Output:</div>
          )}
          {item.result && (
            <pre className="text-[12px] bg-claude-code text-claude-codeText border border-claude-borderSoft rounded-md px-2.5 py-1.5 overflow-x-auto whitespace-pre-wrap break-words max-h-72">
              {item.result.content || '(no output)'}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
