import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import type { CostSummary } from '../types/events'

interface Props {
  sessionId: string | null
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
        if (alive) setError(e instanceof Error ? e.message : String(e))
      }
    })()
    return () => {
      alive = false
    }
  }, [sessionId, refreshKey])

  if (!sessionId || !cost) return null
  if (error) return null

  return (
    <span
      className="text-[12px] font-mono text-claude-textDim px-2 py-0.5 rounded-md bg-claude-panel"
      title={`input ${cost.input_tokens} · output ${cost.output_tokens} · cache_read ${cost.cache_read_tokens}`}
    >
      ${cost.total_cost_usd.toFixed(4)}
    </span>
  )
}
