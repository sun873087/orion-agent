import { useRef, useState } from 'react'
import { Paperclip, Send, Square, X } from 'lucide-react'

import type { Attachment } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'

type Props = {
  onSend: (text: string, attachments?: Attachment[]) => Promise<void>
  onAbort: () => Promise<void>
}

const SUPPORTED_MIME = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
const MAX_BYTES = 20 * 1024 * 1024 // 20 MB raw 上限(再大連 canvas 都吃不下)
// Provider 限制(最嚴的是 Anthropic 5 MB base64);壓到 base64 < 4 MB 留 safety margin
const TARGET_BASE64_BYTES = 4 * 1024 * 1024
const COMPRESS_TRIGGER_BYTES = 1 * 1024 * 1024  // raw 超過 1MB 才走 canvas 壓縮
const COMPRESS_MAX_EDGE = 2048
const COMPRESS_QUALITY = 0.85

/** 多行輸入 + paperclip 上傳 + send / abort 切換。Enter 送出,Shift+Enter 換行。 */
export function InputBox({ onSend, onAbort }: Props) {
  const { t } = useTranslation()
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
  // IME composition tracking — 注音 / 拼音中 Enter 確認候選詞時不要送出。
  const composingRef = useRef(false)

  const canSend =
    !busy && inputReady && (text.trim().length > 0 || attachments.length > 0)

  async function handleSubmit() {
    if (!canSend) return
    const payload = text
    const att = attachments
    setText('')
    setAttachments([])
    setAttachError(null)
    // 直接清 textarea DOM value:避免 IME / React batching 時序 race
    // 讓送出後字符仍殘留在輸入框。
    if (textareaRef.current) {
      textareaRef.current.value = ''
    }
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
        setAttachError(t('input.attach.unsupported', { name: f.name }))
        continue
      }
      if (f.size > MAX_BYTES) {
        setAttachError(t('input.attach.tooBig', { name: f.name }))
        continue
      }
      try {
        // 大圖(> 1MB raw)自動 canvas resize + JPEG re-encode,避免 Anthropic 5 MB
        // base64 上限把 LLM call 打回。人眼幾乎無差(2048px max edge / quality 0.85)。
        const { base64, mediaType } =
          f.size > COMPRESS_TRIGGER_BYTES
            ? await compressImage(f)
            : { base64: await fileToBase64(f), mediaType: f.type }
        added.push({
          media_type: mediaType,
          data: base64,
          preview_url: `data:${mediaType};base64,${base64}`,
          filename: f.name,
        })
      } catch {
        setAttachError(t('input.attach.readFail', { name: f.name }))
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
                  title={t('input.attach.remove')}
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
            title={t('input.attach')}
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
            onCompositionStart={() => {
              composingRef.current = true
            }}
            onCompositionEnd={() => {
              composingRef.current = false
            }}
            onKeyDown={(e) => {
              // IME 在組字中(注音/拼音)按 Enter 是確認候選詞,不是送出。
              // e.nativeEvent.isComposing 是現代瀏覽器 spec;composingRef 雙保險。
              if (e.nativeEvent.isComposing || composingRef.current) return
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
                ? t('input.placeholder.disabled')
                : busy
                  ? t('input.placeholder.busy')
                  : t('input.placeholder.normal')
            }
            rows={1}
            className="scrollbar-thin max-h-[200px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-fg-base placeholder:text-fg-subtle focus:outline-none disabled:cursor-not-allowed"
          />

          {busy ? (
            <button
              type="button"
              onClick={onAbort}
              title={t('input.stop')}
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-error/20 text-error hover:bg-error/30"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSend}
              title={canSend ? t('input.send') : t('input.sendDisabled')}
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
  const { t } = useTranslation()
  const error = useAgentStore((s) => s.error)
  const status = useAgentStore((s) => s.lastLoopStatus)
  if (error) {
    return <p className="mt-1 px-2 text-xs text-error">⚠ {error}</p>
  }
  if (status) {
    const key = status.turns === 1 ? 'input.lastTurn.singular' : 'input.lastTurn'
    return (
      <p className="mt-1 px-2 text-xs text-fg-subtle">
        {t(key, { reason: status.reason, turns: status.turns })}
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

/**
 * Canvas resize + JPEG re-encode 把大圖壓到 base64 < 4 MB(Anthropic 5 MB 限制
 * 留 margin)。先試 1× edge,base64 仍超就遞減 quality / scale 多試幾輪。
 *
 * Trade-off:統一轉 JPEG 會把 PNG 的透明變黑,但 vision LLM 用例幾乎都是
 * 照片 / 截圖,透明資訊不重要。GIF 動畫被 flatten,可接受。
 */
async function compressImage(file: File): Promise<{ base64: string; mediaType: string }> {
  const img = await loadImageFromFile(file)
  const longest = Math.max(img.naturalWidth, img.naturalHeight)
  let scale = longest > COMPRESS_MAX_EDGE ? COMPRESS_MAX_EDGE / longest : 1
  let quality = COMPRESS_QUALITY

  for (let attempt = 0; attempt < 5; attempt++) {
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(img.naturalWidth * scale)
    canvas.height = Math.round(img.naturalHeight * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('canvas 2d context unavailable')
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const dataUrl = canvas.toDataURL('image/jpeg', quality)
    const base64 = dataUrl.split(',')[1] ?? ''
    if (base64.length <= TARGET_BASE64_BYTES) {
      return { base64, mediaType: 'image/jpeg' }
    }
    // 還太大:先降 quality,再降 scale,最後縮到 1280
    if (quality > 0.6) quality -= 0.1
    else if (scale > 0.5) scale *= 0.75
    else scale = 1280 / longest
  }
  throw new Error('cannot compress image under provider limit')
}

function loadImageFromFile(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('image decode failed'))
    }
    img.src = url
  })
}
