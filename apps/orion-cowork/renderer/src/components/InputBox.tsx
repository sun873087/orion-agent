import { useRef, useState } from 'react'
import { Paperclip, Send, Square, X } from 'lucide-react'

import type { Attachment } from '../api/agent'
import { useAgentStore } from '../store/agent'

type Props = {
  onSend: (text: string, attachments?: Attachment[]) => Promise<void>
  onAbort: () => Promise<void>
}

const SUPPORTED_MIME = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
const MAX_BYTES = 20 * 1024 * 1024 // 20 MB / file(provider 多半 cap)

/** 多行輸入 + paperclip 上傳 + send / abort 切換。Enter 送出,Shift+Enter 換行。 */
export function InputBox({ onSend, onAbort }: Props) {
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [attachError, setAttachError] = useState<string | null>(null)
  const busy = useAgentStore((s) => s.busy)
  // sidecar 啟動後一直可輸入;sessionId 為 null(New chat 後)時由 useSendPrompt
  // lazy create。只有 initError(sidecar 連不上)才完全 disable。
  const initError = useAgentStore((s) => s.initError)
  const inputReady = !initError
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const canSend =
    !busy && inputReady && (text.trim().length > 0 || attachments.length > 0)

  async function handleSubmit() {
    if (!canSend) return
    const payload = text
    const att = attachments
    setText('')
    setAttachments([])
    setAttachError(null)
    autoResize()
    await onSend(payload, att.length ? att : undefined)
  }

  function autoResize() {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setAttachError(null)
    const added: Attachment[] = []
    for (const f of Array.from(files)) {
      if (!SUPPORTED_MIME.includes(f.type)) {
        setAttachError(`${f.name}: unsupported (only PNG / JPEG / GIF / WebP)`)
        continue
      }
      if (f.size > MAX_BYTES) {
        setAttachError(`${f.name}: file > 20 MB (provider limit)`)
        continue
      }
      try {
        const base64 = await fileToBase64(f)
        added.push({
          media_type: f.type,
          data: base64,
          preview_url: `data:${f.type};base64,${base64}`,
          filename: f.name,
        })
      } catch {
        setAttachError(`${f.name}: failed to read`)
      }
    }
    if (added.length) setAttachments((prev) => [...prev, ...added])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function removeAttachment(idx: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== idx))
  }

  const [dragOver, setDragOver] = useState(false)

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    if (!inputReady) return
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files)
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    if (!dragOver) setDragOver(true)
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    // 只在離開外層元素時才取消 — 子元素 enter/leave 會觸發父
    if (e.currentTarget === e.target) setDragOver(false)
  }

  return (
    <div
      className={`border-t border-bg-hover bg-bg-base px-6 py-3 transition-colors ${
        dragOver ? 'bg-accent/10 ring-2 ring-inset ring-accent' : ''
      }`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <div className="mx-auto max-w-3xl">
        {/* Attachment thumbnails */}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachments.map((a, i) => (
              <div
                key={i}
                className="relative h-20 w-20 overflow-hidden rounded-lg border border-bg-hover bg-bg-panel"
              >
                <img
                  src={a.preview_url}
                  alt={a.filename || 'attachment'}
                  className="h-full w-full object-cover"
                />
                <button
                  type="button"
                  onClick={() => removeAttachment(i)}
                  className="absolute right-0.5 top-0.5 rounded-full bg-bg-base/80 p-0.5 text-fg-base hover:bg-error/40 hover:text-error"
                  title="Remove"
                >
                  <X size={12} />
                </button>
                {a.filename && (
                  <div
                    className="absolute bottom-0 left-0 right-0 truncate bg-bg-base/70 px-1 text-[10px] text-fg-muted"
                    title={a.filename}
                  >
                    {a.filename}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {attachError && (
          <p className="mb-1 px-2 text-xs text-error">⚠ {attachError}</p>
        )}

        <div className="flex items-end gap-2 rounded-2xl bg-bg-input p-2">
          {/* Paperclip button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={!inputReady || busy}
            title="Attach image (PNG/JPEG/GIF/WebP, max 20 MB each)"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Paperclip size={16} />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={SUPPORTED_MIME.join(',')}
            onChange={(e) => handleFiles(e.target.files)}
            className="hidden"
          />

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
            onPaste={(e) => {
              const items = e.clipboardData?.items
              if (!items) return
              const pasted: File[] = []
              for (const item of items) {
                if (item.kind === 'file') {
                  const f = item.getAsFile()
                  if (f) pasted.push(f)
                }
              }
              if (pasted.length) {
                e.preventDefault()
                const dt = new DataTransfer()
                pasted.forEach((f) => dt.items.add(f))
                handleFiles(dt.files)
              }
            }}
            disabled={!inputReady}
            placeholder={
              !inputReady
                ? 'sidecar unavailable'
                : busy
                  ? 'agent thinking — press Stop to abort'
                  : 'Send a message  (Enter to send · Shift+Enter for newline · paste / drop image to attach)'
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
    return <p className="mt-1 px-2 text-xs text-error">⚠ {error}</p>
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

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        reject(new Error('FileReader returned non-string'))
        return
      }
      const idx = result.indexOf(',')
      resolve(idx >= 0 ? result.slice(idx + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('read error'))
    reader.readAsDataURL(file)
  })
}
