import { useRef, useState } from 'react'
import { Send, Square } from 'lucide-react'

import { useAgentStore } from '../store/agent'

type Props = {
  onSend: (text: string) => Promise<void>
  onAbort: () => Promise<void>
}

/** 多行輸入 + send button(busy 時變 abort)。Enter 送出,Shift+Enter 換行。 */
export function InputBox({ onSend, onAbort }: Props) {
  const [text, setText] = useState('')
  const busy = useAgentStore((s) => s.busy)
  const sessionReady = useAgentStore((s) => !!s.sessionId)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const canSend = !busy && sessionReady && text.trim().length > 0

  async function handleSubmit() {
    if (!canSend) return
    const payload = text
    setText('')
    autoResize() // reset height after clear
    await onSend(payload)
  }

  function autoResize() {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }

  return (
    <div className="border-t border-bg-hover bg-bg-base px-6 py-3">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl bg-bg-input p-2">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              autoResize()
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSubmit()
              }
            }}
            disabled={!sessionReady}
            placeholder={
              !sessionReady
                ? 'initializing…'
                : busy
                  ? 'agent thinking — press Stop to abort'
                  : 'Send a message  (Enter to send, Shift+Enter for newline)'
            }
            rows={1}
            className="scrollbar-thin max-h-[200px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-fg-base placeholder:text-fg-subtle focus:outline-none disabled:cursor-not-allowed"
          />
          {busy ? (
            <button
              type="button"
              onClick={onAbort}
              title="Stop (cancel current turn)"
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-error/20 text-error hover:bg-error/30"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSend}
              title={canSend ? 'Send (Enter)' : 'Type a message first'}
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Send size={14} />
            </button>
          )}
        </div>
        <FooterHint />
      </div>
    </div>
  )
}

function FooterHint() {
  const error = useAgentStore((s) => s.error)
  const status = useAgentStore((s) => s.lastLoopStatus)
  if (error) {
    return (
      <p className="mt-1 px-2 text-xs text-error">⚠ {error}</p>
    )
  }
  if (status) {
    return (
      <p className="mt-1 px-2 text-xs text-fg-subtle">
        last: {status.reason} · {status.turns} {status.turns === 1 ? 'turn' : 'turns'}
      </p>
    )
  }
  return null
}
