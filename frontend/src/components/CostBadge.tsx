import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import type { CostSummary } from '../types/events'

interface Props {
  sessionId: string | null
  /** trigger 重抓的依賴(送完 turn 時 bump 即重新拉);可傳 events.length。 */
  refreshKey?: number | string
}

export function CostBadge({ sessionId, refreshKey }: Props) {
  const [cost, setCost] = useState<CostSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) {
      setCost(null)
      return
    }
    let alive = true
    ;(async () => {
      try {
        const c = await apiFetch<CostSummary>(`/sessions/${sessionId}/cost`)
        if (alive) {
          setCost(c)
          setError(null)
        }
      } catch (e) {
        if (alive) {
          setError(e instanceof Error ? e.message : String(e))
        }
      }
    })()
    return () => {
      alive = false
    }
  }, [sessionId, refreshKey])

  if (!sessionId) {
    return <span className="text-xs text-gray-400">no session</span>
  }
  if (error) {
    return (
      <span
        className="text-xs text-red-500"
        title={error}
      >
        cost ?
      </span>
    )
  }
  if (!cost) {
    return <span className="text-xs text-gray-400">loading…</span>
  }
  return (
    <span
      className="text-xs text-gray-700 font-mono"
      title={`input ${cost.input_tokens} · output ${cost.output_tokens} · cache_read ${cost.cache_read_tokens}`}
    >
      $
      {cost.total_cost_usd.toFixed(4)}
    </span>
  )
}
