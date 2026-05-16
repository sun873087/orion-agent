import { useEffect, useState } from 'react'
import { AlertCircle, Plug, PlugZap, RotateCw } from 'lucide-react'

import { fetchMcpStatus, reconnectMcp, type McpStatus } from '../../api/agent'
import { useTranslation } from '../../i18n'

export function McpSection() {
  const { t } = useTranslation()
  const [status, setStatus] = useState<McpStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [reconnecting, setReconnecting] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      setStatus(await fetchMcpStatus())
    } catch {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function handleReconnect(name: string) {
    setReconnecting(name)
    try {
      await reconnectMcp(name)
      await refresh()
    } finally {
      setReconnecting(null)
    }
  }

  if (loading && !status) {
    return <div className="text-sm text-fg-muted">{t('settings.mcp.loading')}</div>
  }
  if (!status) {
    return <div className="text-sm text-error">{t('settings.mcp.failed')}</div>
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-fg-subtle">
        {t('settings.mcp.config')} <code className="font-mono">{status.config_path}</code>
        <button
          type="button"
          onClick={refresh}
          className="ml-2 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          title={t('settings.mcp.refreshTitle')}
        >
          <RotateCw size={11} />
          <span>{t('settings.mcp.refresh')}</span>
        </button>
      </div>
      {status.servers.length === 0 ? (
        <div className="whitespace-pre-line rounded-lg border border-dashed border-bg-hover p-3 text-center text-xs text-fg-subtle">
          {t('settings.mcp.none')}
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {status.servers.map((s) => (
            <li
              key={s.name}
              className="flex items-center justify-between gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-2"
            >
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <StatusIcon status={s.status} />
                <div className="min-w-0 flex-1">
                  <div className="font-mono text-sm text-fg-base">{s.name}</div>
                  {s.status === 'connected' && (
                    <div className="text-xs text-fg-subtle">
                      {t('settings.mcp.tools', { n: s.tools.length })}
                    </div>
                  )}
                  {s.error && (
                    <div className="truncate text-xs text-error" title={s.error}>
                      {s.error}
                    </div>
                  )}
                </div>
              </div>
              {s.status !== 'connected' && (
                <button
                  type="button"
                  onClick={() => handleReconnect(s.name)}
                  disabled={reconnecting === s.name}
                  className="rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:opacity-40"
                  title={t('settings.mcp.reconnect')}
                >
                  <RotateCw size={14} className={reconnecting === s.name ? 'animate-spin' : ''} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function StatusIcon({ status }: { status: McpStatus['servers'][number]['status'] }) {
  if (status === 'connected') return <PlugZap size={14} className="text-success" />
  if (status === 'pending') return <Plug size={14} className="text-fg-muted" />
  return <AlertCircle size={14} className="text-warning" />
}
