import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'

export function SettingsPanel() {
  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const [unavailable, setUnavailable] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    setError(null)
    try {
      const all = await apiFetch<Record<string, unknown>>('/me/settings')
      setSettings(all || {})
      setUnavailable(false)
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        setUnavailable(true)
      } else {
        setError(e instanceof Error ? e.message : String(e))
      }
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function setKey() {
    if (!newKey) return
    setBusy(true)
    setError(null)
    try {
      let parsed: unknown
      try {
        parsed = JSON.parse(newValue)
      } catch {
        parsed = newValue // 純字串
      }
      await apiFetch(`/me/settings/${encodeURIComponent(newKey)}`, {
        method: 'PUT',
        body: { value: parsed },
      })
      setNewKey('')
      setNewValue('')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function deleteKey(key: string) {
    if (!confirm(`Delete setting "${key}"?`)) return
    setBusy(true)
    try {
      await apiFetch(`/me/settings/${encodeURIComponent(key)}`, {
        method: 'DELETE',
      })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (unavailable) {
    return (
      <div className="text-sm text-gray-500 p-3">
        Settings require <code>ORION_DB_URL</code> on the backend.
      </div>
    )
  }

  return (
    <div className="p-3 space-y-3 text-sm">
      <div className="font-semibold">User Settings</div>

      {error && (
        <div className="text-red-600 bg-red-50 p-2 rounded text-xs">
          {error}
        </div>
      )}

      <div className="space-y-2">
        {Object.keys(settings).length === 0 && (
          <div className="text-xs text-gray-500">(empty)</div>
        )}
        {Object.entries(settings).map(([key, value]) => (
          <div
            key={key}
            className="border border-gray-200 rounded p-2 bg-gray-50 flex items-start justify-between gap-2"
          >
            <div className="flex-1 min-w-0">
              <div className="font-mono text-xs font-semibold">{key}</div>
              <pre className="text-xs text-gray-700 whitespace-pre-wrap break-all mt-0.5">
                {JSON.stringify(value)}
              </pre>
            </div>
            <button
              onClick={() => void deleteKey(key)}
              className="text-gray-400 hover:text-red-600 text-sm"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="border-t border-gray-200 pt-3 space-y-1">
        <div className="font-semibold text-xs">Add / Update</div>
        <input
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs font-mono"
          placeholder="key (e.g. model)"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
        />
        <input
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs font-mono"
          placeholder='value (JSON or string, e.g. "claude-opus-4-7")'
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
        />
        <button
          onClick={() => void setKey()}
          disabled={busy || !newKey}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white rounded py-1 text-xs disabled:bg-gray-300"
        >
          Save
        </button>
      </div>
    </div>
  )
}
