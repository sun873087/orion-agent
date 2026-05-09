import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../api/client'

export interface WorkspaceFile {
  name: string
  size: number
  mtime: number
}

export function useSessionFiles(sessionId: string | null, refreshKey: number) {
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setFiles([])
      return
    }
    try {
      const list = await apiFetch<WorkspaceFile[]>(
        `/sessions/${sessionId}/files`,
      )
      setFiles(list || [])
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [sessionId])

  useEffect(() => {
    void refresh()
  }, [refresh, refreshKey])

  return { files, error, refresh }
}
