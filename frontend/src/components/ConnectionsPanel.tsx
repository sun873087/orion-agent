import { useEffect, useRef, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'

interface ProviderInfo {
  name: string
  label: string
  available: boolean
}

interface StatusInfo extends ProviderInfo {
  server: string
  connected: boolean
}

interface StartResponse {
  authorize_url: string
  state: string
}

export function ConnectionsPanel() {
  const [statuses, setStatuses] = useState<StatusInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyServer, setBusyServer] = useState<string | null>(null)
  const pollTimer = useRef<number | null>(null)

  async function refresh() {
    setError(null)
    try {
      const providers = await apiFetch<ProviderInfo[]>('/oauth/providers')
      const settled = await Promise.all(
        providers.map(async (p) => {
          try {
            return await apiFetch<StatusInfo>(
              `/oauth/status/${encodeURIComponent(p.name)}`,
            )
          } catch {
            return {
              ...p,
              server: p.name,
              connected: false,
            } as StatusInfo
          }
        }),
      )
      setStatuses(settled)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    return () => {
      if (pollTimer.current !== null) {
        window.clearInterval(pollTimer.current)
      }
    }
  }, [])

  async function connect(server: string) {
    setError(null)
    setBusyServer(server)
    try {
      const resp = await apiFetch<StartResponse>('/oauth/start', {
        method: 'POST',
        body: { server },
      })
      // 開新窗讓 user 完成授權
      const popup = window.open(
        resp.authorize_url,
        'orion-oauth',
        'width=600,height=720,menubar=no,toolbar=no',
      )
      if (!popup) {
        setError(
          'Popup blocked. Allow popups for this site and try again.',
        )
        setBusyServer(null)
        return
      }
      // poll status 直到看到 connected,或 popup 被使用者關掉
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current)
      const startedAt = Date.now()
      pollTimer.current = window.setInterval(async () => {
        try {
          const st = await apiFetch<StatusInfo>(
            `/oauth/status/${encodeURIComponent(server)}`,
          )
          if (st.connected) {
            stopPolling()
            await refresh()
            try {
              popup.close()
            } catch {
              /* cross-origin close 可能 silently fail,沒關係 */
            }
          } else if (popup.closed) {
            stopPolling()
            setError('OAuth window closed before connection completed.')
          } else if (Date.now() - startedAt > 5 * 60 * 1000) {
            stopPolling()
            setError('OAuth timed out after 5 minutes.')
          }
        } catch (e) {
          stopPolling()
          setError(e instanceof Error ? e.message : String(e))
        }
      }, 1500)
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? `${e.message} (HTTP ${e.status})`
          : e instanceof Error
            ? e.message
            : String(e)
      setError(msg)
      setBusyServer(null)
    }
  }

  function stopPolling() {
    if (pollTimer.current !== null) {
      window.clearInterval(pollTimer.current)
      pollTimer.current = null
    }
    setBusyServer(null)
  }

  async function disconnect(server: string) {
    if (!confirm(`Disconnect ${server}? Stored token will be deleted.`)) return
    setError(null)
    try {
      await apiFetch(`/oauth/${encodeURIComponent(server)}`, {
        method: 'DELETE',
      })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="p-6 space-y-4 text-[14px]">
      <div>
        <div className="font-medium text-claude-text">Connections</div>
        <div className="text-[12px] text-claude-textDim">
          OAuth tokens are stored in your OS credential store (macOS
          Keychain, Windows Credential Manager, or Linux Secret Service —
          search{' '}
          <span className="font-mono text-[11px]">orion-agent</span>).
          Falls back to encrypted file{' '}
          <code className="font-mono text-[11px] bg-claude-code px-1 py-0.5 rounded">
            ~/.orion/secrets.enc
          </code>{' '}
          when no keychain is available or{' '}
          <code className="font-mono text-[11px] bg-claude-code px-1 py-0.5 rounded">
            ORION_DISABLE_KEYCHAIN=1
          </code>
          .
        </div>
      </div>

      {error && (
        <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-[13px] text-claude-textDim italic">Loading…</div>
      ) : (
        <div className="space-y-1.5">
          {statuses.map((s) => (
            <ConnectionRow
              key={s.server}
              status={s}
              busy={busyServer === s.server}
              onConnect={() => void connect(s.server)}
              onDisconnect={() => void disconnect(s.server)}
            />
          ))}
        </div>
      )}

      <div className="text-[12px] text-claude-textFaint pt-2 border-t border-claude-border/60">
        Add real providers by setting{' '}
        <code className="font-mono text-[11px] bg-claude-code px-1 py-0.5 rounded">
          GITHUB_OAUTH_CLIENT_ID
        </code>
        {' / '}
        <code className="font-mono text-[11px] bg-claude-code px-1 py-0.5 rounded">
          _SECRET
        </code>
        {' (and equivalents) on the backend, then redirect-URI '}
        <code className="font-mono text-[11px] bg-claude-code px-1 py-0.5 rounded">
          {window.location.origin}/oauth/callback
        </code>{' '}
        on the OAuth app config.
      </div>
    </div>
  )
}

interface RowProps {
  status: StatusInfo
  busy: boolean
  onConnect: () => void
  onDisconnect: () => void
}

function ConnectionRow({ status, busy, onConnect, onDisconnect }: RowProps) {
  const disabled = !status.available && !status.connected
  return (
    <div className="flex items-center gap-3 p-3 rounded-md bg-white dark:bg-claude-panel border border-claude-borderSoft">
      <div className="shrink-0 h-8 w-8 inline-flex items-center justify-center rounded-md bg-claude-orange/10 text-claude-orange text-[13px] font-semibold">
        {status.label.charAt(0)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-claude-text">{status.label}</div>
        <div className="text-[12px] text-claude-textDim">
          {status.connected ? (
            <span className="text-emerald-700 dark:text-emerald-400">
              ✓ Connected
            </span>
          ) : disabled ? (
            <span className="text-claude-textFaint italic">
              Not configured (env vars missing)
            </span>
          ) : (
            <span>Not connected</span>
          )}
        </div>
      </div>
      {status.connected ? (
        <button
          onClick={onDisconnect}
          className="px-3 py-1.5 border border-claude-border text-claude-textDim hover:text-red-700 dark:hover:text-red-300 hover:border-red-200 dark:hover:border-red-900/60 rounded-md text-[13px] transition-colors"
        >
          Disconnect
        </button>
      ) : (
        <button
          onClick={onConnect}
          disabled={disabled || busy}
          className="px-3 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint disabled:cursor-not-allowed text-white rounded-md text-[13px] font-medium transition-colors"
        >
          {busy ? 'Waiting…' : 'Connect'}
        </button>
      )}
    </div>
  )
}
