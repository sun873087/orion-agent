/** Project state — 直接掛 in-module state(輕量,目前 UI 只一處顯示)。 */
import { useCallback, useEffect, useSyncExternalStore } from 'react'

import { listProjects, type Project } from '../api/agent'

let _projects: Project[] = []
let _loading = false
const _listeners = new Set<() => void>()

function emit() {
  for (const l of _listeners) l()
}

async function fetchProjects() {
  if (_loading) return
  _loading = true
  try {
    _projects = await listProjects()
  } catch {
    _projects = []
  } finally {
    _loading = false
    emit()
  }
}

function subscribe(cb: () => void) {
  _listeners.add(cb)
  return () => _listeners.delete(cb)
}

function getSnapshot(): Project[] {
  return _projects
}

export function useProjects(): Project[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

export function useReloadProjects() {
  return useCallback(async () => {
    await fetchProjects()
  }, [])
}

/** 一次性掛載:app 啟動 + Settings page 不在時都 load 一次。 */
export function useLoadProjectsOnce() {
  useEffect(() => {
    fetchProjects()
  }, [])
}
