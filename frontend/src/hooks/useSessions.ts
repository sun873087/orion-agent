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
        await refresh()
        return s
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      }
    },
    [refresh],
  )

  const remove = useCallback(
    async (sessionId: string) => {
      try {
        await apiFetch(`/sessions/${sessionId}`, { method: 'DELETE' })
        await refresh()
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    },
    [refresh],
  )

  useEffect(() => {
    void refresh()
  }, [refresh])

  return { sessions, loading, error, refresh, create, remove }
}
