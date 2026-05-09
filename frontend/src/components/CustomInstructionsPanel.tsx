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
      <div className="p-6 text-[14px] text-claude-textDim">
        Custom Instructions require{' '}
        <code className="font-mono text-[12px] bg-claude-code px-1.5 py-0.5 rounded">
          ORION_DB_URL
        </code>{' '}
        on the backend.
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5 text-[14px]">
      <Section
        label="About you"
        hint="Persistent across all conversations. Tell Orion how to address you, your role, your preferences."
      >
        <textarea
          className="w-full h-32 border border-claude-border rounded-lg p-3 text-[13px] bg-white focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow resize-none"
          placeholder="e.g. I'm a senior Python engineer; prefer terse explanations."
          value={user}
          onChange={(e) => setUser(e.target.value)}
        />
      </Section>

      <Section
        label="This conversation"
        hint={
          sessionId
            ? 'Applies only to the current conversation.'
            : 'Select a conversation to set context-specific instructions.'
        }
      >
        <textarea
          className="w-full h-32 border border-claude-border rounded-lg p-3 text-[13px] bg-white focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow resize-none disabled:bg-claude-panel/40"
          placeholder="e.g. Reviewing a Python migration script; focus on safety."
          value={conv}
          onChange={(e) => setConv(e.target.value)}
          disabled={!sessionId}
        />
      </Section>

      {error && (
        <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between pt-1">
        <div className="text-[12px] text-claude-textFaint">
          {savedAt && (
            <span className="text-emerald-700">
              ✓ Saved {new Date(savedAt).toLocaleTimeString()}
            </span>
          )}
        </div>
        <button
          onClick={() => void save()}
          disabled={busy}
          className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
        >
          {busy ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}

function Section({
  label,
  hint,
  children,
}: {
  label: string
  hint: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <div className="font-medium text-claude-text text-[13px]">{label}</div>
      <div className="text-[12px] text-claude-textDim">{hint}</div>
      <div className="pt-1">{children}</div>
    </div>
  )
}
