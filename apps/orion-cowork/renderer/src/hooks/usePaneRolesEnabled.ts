/** Per-role 開關 — 哪些 role 名稱被 user 關閉。
 *
 *  Source of truth:`cowork_prefs.disabled_roles` 是 CSV 字串(空 = 全部 enabled)。
 *  e.g. "reviewer,researcher" → 這兩個 role 不會 inject prompt / 套 disabled_tools。
 *  Role 仍可被選 / 顯示,只是對 LLM 行為無效果(等同 custom)。
 */
import { useCallback, useEffect, useState } from 'react'

import { getPrefs, setPref } from '../api/agent'

export const DISABLED_ROLES_PREF_KEY = 'disabled_roles'

function parseSet(raw: string | undefined): Set<string> {
  if (!raw) return new Set()
  return new Set(raw.split(',').map((s) => s.trim()).filter(Boolean))
}

function serializeSet(s: Set<string>): string {
  return Array.from(s).sort().join(',')
}

export function useDisabledRoles(): {
  disabled: Set<string>
  isDisabled: (name: string) => boolean
  setRoleEnabled: (name: string, enabled: boolean) => Promise<void>
  loading: boolean
} {
  const [disabled, setDisabledState] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const prefs = await getPrefs()
        const raw = prefs[DISABLED_ROLES_PREF_KEY]
        if (!cancelled) setDisabledState(parseSet(raw))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
  }, [])

  const isDisabled = useCallback((name: string) => disabled.has(name), [disabled])

  const setRoleEnabled = useCallback(
    async (name: string, enabled: boolean) => {
      // Optimistic
      const next = new Set(disabled)
      if (enabled) next.delete(name)
      else next.add(name)
      setDisabledState(next)
      try {
        await setPref(DISABLED_ROLES_PREF_KEY, serializeSet(next))
      } catch {
        // 失敗回滾
        setDisabledState(disabled)
      }
    },
    [disabled],
  )

  return { disabled, isDisabled, setRoleEnabled, loading }
}
