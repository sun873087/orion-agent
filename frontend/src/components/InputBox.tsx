import { useRef, useState } from 'react'
import { apiUpload } from '../api/client'
import type { UploadSummary } from '../types/events'

interface Props {
  disabled: boolean
  onSend: (text: string, attachments: UploadSummary[]) => void
  onAbort: () => void
}

export function InputBox({ disabled, onSend, onAbort }: Props) {
  const [text, setText] = useState('')
  const [pendingFiles, setPendingFiles] = useState<UploadSummary[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  async function uploadFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setError(null)
    setUploading(true)
    try {
      const list: UploadSummary[] = []
      for (const f of Array.from(files)) {
        const fd = new FormData()
        fd.append('file', f)
        const u = await apiUpload<UploadSummary>('/uploads', fd)
        list.push(u)
      }
      setPendingFiles((prev) => [...prev, ...list])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
    }
  }

  function send() {
    const t = text.trim()
    if (!t && pendingFiles.length === 0) return
    onSend(t, pendingFiles)
    setText('')
    setPendingFiles([])
    if (fileRef.current) fileRef.current.value = ''
    if (taRef.current) taRef.current.style.height = 'auto'
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault()
      send()
    }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      send()
    }
  }

  function autoGrow(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setText(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 240)}px`
  }

  function removeFile(id: string) {
    setPendingFiles((prev) => prev.filter((f) => f.upload_id !== id))
  }

  // 阻止 textarea / 任何子元素 native drop(否則拖檔會被瀏覽器導航 / 變字串塞進 textarea = GG)
  const stop = (e: React.DragEvent | React.SyntheticEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  return (
    <div
      className="px-4 pb-4 pt-2"
      onDragEnter={(e) => {
        stop(e)
        setDragActive(true)
      }}
      onDragOver={stop}
      onDragLeave={(e) => {
        // 只在離開最外層 wrapper 時關 highlight,進子元素不關
        if (e.currentTarget === e.target) setDragActive(false)
      }}
      onDrop={(e) => {
        stop(e)
        setDragActive(false)
        void uploadFiles(e.dataTransfer.files)
      }}
    >
      <div className="max-w-3xl mx-auto">
        {error && (
          <div className="mb-2 text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-1.5 rounded-md">
            {error}
          </div>
        )}

        <div
          className={`relative rounded-2xl bg-white dark:bg-claude-panel shadow-input dark:shadow-none dark:ring-1 dark:ring-claude-border transition-shadow ${
            dragActive ? 'ring-2 ring-claude-orange/40' : ''
          }`}
        >
          {pendingFiles.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-3">
              {pendingFiles.map((f) => (
                <span
                  key={f.upload_id}
                  className="inline-flex items-center gap-1.5 text-[12px] bg-claude-panel border border-claude-border rounded-full pl-2.5 pr-1 py-1"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 16 16"
                    fill="none"
                    className="text-claude-textDim"
                  >
                    <path
                      d="M10 3v6.5a2.5 2.5 0 11-5 0V4a1.5 1.5 0 113 0v5.5a.5.5 0 11-1 0V4.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                  {f.filename}
                  <span className="text-claude-textFaint">
                    {Math.round(f.size / 1024)}KB
                  </span>
                  <button
                    className="ml-1 h-4 w-4 inline-flex items-center justify-center rounded-full text-claude-textFaint hover:bg-claude-border hover:text-claude-text"
                    onClick={() => removeFile(f.upload_id)}
                    aria-label="remove"
                  >
                    <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                      <path
                        d="M2 2l4 4M6 2l-4 4"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                </span>
              ))}
            </div>
          )}

          <textarea
            ref={taRef}
            className="w-full resize-none px-4 pt-3 pb-1 text-[15px] leading-relaxed placeholder:text-claude-textFaint focus:outline-none"
            placeholder="Reply to Orion…"
            rows={1}
            value={text}
            onChange={autoGrow}
            onKeyDown={onKeyDown}
            // textarea native drop 預設會把檔案 URL / 路徑塞成 text — 必須擋掉,讓外層 wrapper 處理
            onDragOver={stop}
            onDrop={(e) => {
              stop(e)
              setDragActive(false)
              void uploadFiles(e.dataTransfer.files)
            }}
            disabled={disabled}
            style={{ maxHeight: 240 }}
          />

          <div className="flex items-center gap-1 px-2.5 pb-2.5">
            <button
              className="p-2 rounded-lg text-claude-textDim hover:bg-claude-panel hover:text-claude-text disabled:opacity-50 transition-colors"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              title="Attach file"
            >
              {uploading ? (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <circle
                    cx="8"
                    cy="8"
                    r="6"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeOpacity="0.3"
                  />
                  <path
                    d="M14 8a6 6 0 00-6-6"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    className="origin-center"
                    style={{
                      animation: 'spin 1s linear infinite',
                      transformOrigin: 'center',
                    }}
                  />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M11.5 8L8.5 11a2 2 0 11-2.83-2.83l4-4a3.5 3.5 0 014.95 4.95l-5.62 5.62a5 5 0 01-7.07-7.07l4-4"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>
            <input
              ref={fileRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => void uploadFiles(e.target.files)}
            />

            <div className="ml-auto flex items-center gap-1.5">
              {disabled && (
                <button
                  className="px-3 py-1.5 text-[13px] text-claude-textDim hover:text-red-600 transition-colors"
                  onClick={onAbort}
                >
                  Stop
                </button>
              )}
              <button
                className="h-8 w-8 inline-flex items-center justify-center rounded-lg bg-claude-orange text-white hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint disabled:cursor-not-allowed transition-colors"
                onClick={send}
                disabled={
                  disabled || (!text.trim() && pendingFiles.length === 0)
                }
                title="Send (Enter)"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M8 13V3M3 8l5-5 5 5"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <div className="mt-1.5 px-1 text-[11px] text-claude-textFaint text-center">
          Enter to send · Shift+Enter for newline · drop files to attach
        </div>
      </div>
    </div>
  )
}
