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
  const fileRef = useRef<HTMLInputElement>(null)

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
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      send()
    }
  }

  function removeFile(id: string) {
    setPendingFiles((prev) => prev.filter((f) => f.upload_id !== id))
  }

  return (
    <div
      className="border-t border-gray-200 bg-white p-3 space-y-2"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault()
        void uploadFiles(e.dataTransfer.files)
      }}
    >
      {error && (
        <div className="text-sm text-red-600 bg-red-50 px-2 py-1 rounded">
          {error}
        </div>
      )}

      {pendingFiles.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {pendingFiles.map((f) => (
            <span
              key={f.upload_id}
              className="text-xs bg-gray-100 border border-gray-300 rounded px-2 py-1 flex items-center gap-1"
            >
              📎 {f.filename}{' '}
              <span className="text-gray-400">
                ({Math.round(f.size / 1024)} KB)
              </span>
              <button
                className="ml-1 text-gray-500 hover:text-red-600"
                onClick={() => removeFile(f.upload_id)}
                aria-label="remove"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex gap-2 items-end">
        <textarea
          className="flex-1 border border-gray-300 rounded px-3 py-2 font-mono text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-300"
          placeholder="Type a message... (⌘/Ctrl + Enter to send, drop files anywhere)"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
        />
        <div className="flex flex-col gap-1">
          <button
            className="px-3 py-1 bg-gray-200 hover:bg-gray-300 rounded text-sm whitespace-nowrap"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? '⏳' : '📎'} Upload
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => void uploadFiles(e.target.files)}
          />
          <button
            className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm disabled:bg-gray-300"
            onClick={send}
            disabled={disabled || (!text.trim() && pendingFiles.length === 0)}
          >
            Send
          </button>
          {disabled && (
            <button
              className="px-3 py-1 bg-orange-500 hover:bg-orange-600 text-white rounded text-sm"
              onClick={onAbort}
            >
              ✗ Abort
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
