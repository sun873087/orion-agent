import { useState } from 'react'
import { useSessionFiles } from '../hooks/useSessionFiles'
import { getToken } from '../api/auth'

interface Props {
  sessionId: string | null
  refreshKey: number
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function downloadFile(sessionId: string, name: string) {
  // 用 fetch + Authorization header,blob 化後觸發下載
  const r = await fetch(`/sessions/${sessionId}/files/${encodeURIComponent(name)}`, {
    headers: { Authorization: `Bearer ${getToken() ?? ''}` },
  })
  if (!r.ok) {
    alert(`download failed: HTTP ${r.status}`)
    return
  }
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function WorkspaceFiles({ sessionId, refreshKey }: Props) {
  const [open, setOpen] = useState(false)
  const { files } = useSessionFiles(sessionId, refreshKey)

  if (!sessionId) return null
  if (files.length === 0) return null

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2 py-1 text-[12px] rounded-md bg-claude-panel text-claude-textDim hover:bg-claude-borderSoft hover:text-claude-text transition-colors"
        title="Generated files in this session's workspace"
      >
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
          <path
            d="M3 4a1 1 0 011-1h3l1 1.5h4a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1V4z"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
        </svg>
        <span>{files.length} {files.length === 1 ? 'file' : 'files'}</span>
      </button>

      {open && (
        <div className="absolute right-0 mt-1.5 w-72 max-h-72 overflow-y-auto bg-white dark:bg-claude-panel border border-claude-border rounded-lg shadow-lg dark:shadow-[0_10px_30px_-8px_rgba(0,0,0,0.5)] z-20 py-1">
          <div className="px-3 py-1.5 text-[11px] uppercase tracking-wide text-claude-textFaint border-b border-claude-borderSoft">
            Workspace
          </div>
          {files.map((f) => (
            <button
              key={f.name}
              className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-claude-cream"
              onClick={() => void downloadFile(sessionId, f.name)}
            >
              <span className="font-mono text-claude-text truncate">{f.name}</span>
              <span className="text-[11px] text-claude-textFaint shrink-0">
                {fmtSize(f.size)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
