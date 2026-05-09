import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import type { CustomInstructionsResponse } from '../types/events'

interface Props {
  sessionId: string | null
}

export function CustomInstructionsPanel({ sessionId }: Props) {
  const [user, setUser] = useState('')
  const [conv, setConv] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    setError(null)
    setUnavailable(false)
    ;(async () => {
      try {
        const me = await apiFetch<CustomInstructionsResponse>(
          '/me/custom-instructions',
        )
        if (alive) setUser(me.user_level ?? '')
        if (sessionId) {
          const sc = await apiFetch<CustomInstructionsResponse>(
            `/sessions/${sessionId}/custom-instructions`,
          )
          if (alive) setConv(sc.conversation_level ?? '')
        } else if (alive) {
          setConv('')
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 503) {
          if (alive) setUnavailable(true)
        } else if (alive) {
          setError(e instanceof Error ? e.message : String(e))
        }
      }
    })()
    return () => {
      alive = false
    }
  }, [sessionId])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await apiFetch('/me/custom-instructions', {
        method: 'PUT',
        body: { instructions: user || null },
      })
      if (sessionId) {
        await apiFetch(`/sessions/${sessionId}/custom-instructions`, {
          method: 'PUT',
          body: { instructions: conv || null },
        })
      }
      setSavedAt(Date.now())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (unavailable) {
    return (
      <div className="text-sm text-gray-500 p-3">
        Custom Instructions require <code>ORION_DB_URL</code> on the backend.
      </div>
    )
  }

  return (
    <div className="p-3 space-y-3 text-sm">
      <div>
        <div className="font-semibold mb-1">About you (per-user)</div>
        <textarea
          className="w-full h-32 border border-gray-300 rounded p-2 text-sm font-mono"
          placeholder="e.g. I'm a senior Python engineer; prefer terse explanations."
          value={user}
          onChange={(e) => setUser(e.target.value)}
        />
      </div>

      <div>
        <div className="font-semibold mb-1">
          This conversation context{' '}
          {!sessionId && (
            <span className="text-xs text-gray-400">(select a session)</span>
          )}
        </div>
        <textarea
          className="w-full h-32 border border-gray-300 rounded p-2 text-sm font-mono disabled:bg-gray-50"
          placeholder="e.g. Reviewing a Python migration script; focus on safety."
          value={conv}
          onChange={(e) => setConv(e.target.value)}
          disabled={!sessionId}
        />
      </div>

      {error && (
        <div className="text-red-600 bg-red-50 p-2 rounded text-xs">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <button
          onClick={() => void save()}
          disabled={busy}
          className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm disabled:bg-gray-300"
        >
          {busy ? 'Saving…' : 'Save'}
        </button>
        {savedAt && (
          <span className="text-xs text-green-600">
            ✓ saved {new Date(savedAt).toLocaleTimeString()}
          </span>
        )}
      </div>
    </div>
  )
}
