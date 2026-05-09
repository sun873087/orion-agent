import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import type { ModelCatalog } from '../types/events'

let _cache: ModelCatalog | null = null
let _inflight: Promise<ModelCatalog> | null = null

async function fetchCatalog(): Promise<ModelCatalog> {
  if (_cache) return _cache
  if (_inflight) return _inflight
  _inflight = apiFetch<ModelCatalog>('/models')
    .then((c) => {
      _cache = c
      return c
    })
    .finally(() => {
      _inflight = null
    })
  return _inflight
}

export function resetModelCatalogCache(): void {
  _cache = null
}

export function useModelCatalog(): {
  catalog: ModelCatalog | null
  loading: boolean
  error: string | null
} {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(_cache)
  const [loading, setLoading] = useState(_cache === null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    if (_cache) {
      setCatalog(_cache)
      setLoading(false)
      return
    }
    setLoading(true)
    fetchCatalog()
      .then((c) => {
        if (alive) {
          setCatalog(c)
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  return { catalog, loading, error }
}
