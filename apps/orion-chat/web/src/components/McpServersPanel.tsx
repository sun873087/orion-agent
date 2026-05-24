import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import { useTranslation } from '../i18n'

interface McpServer {
  name: string
  transport: string
  url: string
}

const inputCls =
  'border border-claude-border rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-claude-cream text-claude-text placeholder:text-claude-textFaint focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow'

export function McpServersPanel() {
  const { t } = useTranslation()
  const [items, setItems] = useState<McpServer[]>([])
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [transport, setTransport] = useState<'http' | 'sse' | 'ws'>('http')
  const [url, setUrl] = useState('')

  async function refresh() {
    try {
      setItems(await apiFetch<McpServer[]>('/mcp/servers'))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function add() {
    if (!name.trim() || !url.trim()) return
    setError(null)
    try {
      await apiFetch(`/mcp/servers/${encodeURIComponent(name.trim())}`, {
        method: 'PUT',
        body: { transport, url: url.trim() },
      })
      setName('')
      setUrl('')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function remove(n: string) {
    await apiFetch(`/mcp/servers/${encodeURIComponent(n)}`, {
      method: 'DELETE',
    }).catch(() => {})
    await refresh()
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="font-medium text-claude-text text-[13px]">
          {t('mcp.title')}
        </div>
        <div className="text-[12px] text-claude-textDim">{t('mcp.desc')}</div>
      </div>

      {error && (
        <div className="text-[12px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <input
          className={`${inputCls} font-mono w-32`}
          placeholder={t('mcp.namePlaceholder')}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select
          className={inputCls}
          value={transport}
          onChange={(e) =>
            setTransport(e.target.value as 'http' | 'sse' | 'ws')
          }
        >
          <option value="http">http</option>
          <option value="sse">sse</option>
          <option value="ws">ws</option>
        </select>
        <input
          className={`${inputCls} font-mono flex-1 min-w-[180px]`}
          placeholder="https://…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button
          onClick={() => void add()}
          disabled={!name.trim() || !url.trim()}
          className="px-3 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
        >
          {t('common.new')}
        </button>
      </div>

      {items.length === 0 ? (
        <div className="text-[12px] text-claude-textFaint italic">
          {t('mcp.empty')}
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((s) => (
            <div
              key={s.name}
              className="group flex items-center gap-3 p-2.5 rounded-md bg-white dark:bg-claude-panel border border-claude-borderSoft"
            >
              <span className="font-mono text-[12px] font-medium">
                {s.name}
              </span>
              <span className="text-[11px] px-1.5 py-0.5 rounded bg-claude-borderSoft text-claude-textDim">
                {s.transport}
              </span>
              <span className="flex-1 min-w-0 truncate text-[12px] text-claude-textDim font-mono">
                {s.url}
              </span>
              <button
                className="opacity-0 group-hover:opacity-100 p-1 text-claude-textFaint hover:text-red-600 transition"
                onClick={() => void remove(s.name)}
                aria-label={t('common.delete')}
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M4 4l8 8M12 4l-8 8"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
