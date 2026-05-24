import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import type { ModelCatalog } from '../types/events'

let _cache: ModelCatalog | null = null
let _inflight: Promise<ModelCatalog> | null = null

async function fetchCatalog(force = false): Promise<ModelCatalog> {
  // 非 force:有 cache / in-flight 就重用。force(開新對話):一律真的重抓 /models。
  if (!force) {
    if (_cache) return _cache
    if (_inflight) return _inflight
  }
  const p = apiFetch<ModelCatalog>('/models').then((c) => {
    _cache = c
    return c
  })
  _inflight = p.finally(() => {
    _inflight = null
  })
  return p
}

export function resetModelCatalogCache(): void {
  _cache = null
}

export function useModelCatalog(): {
  catalog: ModelCatalog | null
  loading: boolean
  error: string | null
  /** 強制重抓 /models(開新對話時用 — provider key / Ollama 模型可能已變)。 */
  refresh: () => void
} {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(_cache)
  const [loading, setLoading] = useState(_cache === null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback((force: boolean) => {
    setLoading(true)
    return fetchCatalog(force)
      .then((c) => {
        setCatalog(c)
        setError(null)
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

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

  const refresh = useCallback(() => void load(true), [load])

  return { catalog, loading, error, refresh }
}
