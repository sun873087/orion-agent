import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import type { SessionSummary } from '../types/events'
import type { ModelChoice } from '../lib/preferredModel'

export function useSessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await apiFetch<SessionSummary[]>('/sessions')
      setSessions(list || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const create = useCallback(
    async (choice?: ModelChoice): Promise<SessionSummary | null> => {
      try {
        const s = await apiFetch<SessionSummary>('/sessions', {
          method: 'POST',
          body: choice ? { provider: choice.provider, model: choice.model } : undefined,
        })
        // Prepend the new session immediately — avoids a second GET /sessions round-trip.
        setSessions((prev) => [s, ...prev.filter((p) => p.session_id !== s.session_id)])
        return s
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      }
    },
    [],
  )

  const remove = useCallback(async (sessionId: string) => {
    // Optimistic remove — UI updates instantly, rollback on failure.
    let snapshot: SessionSummary[] = []
    setSessions((prev) => {
      snapshot = prev
      return prev.filter((s) => s.session_id !== sessionId)
    })
    try {
      await apiFetch(`/sessions/${sessionId}`, { method: 'DELETE' })
    } catch (e) {
      setSessions(snapshot)
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { sessions, loading, error, refresh, create, remove }
}
