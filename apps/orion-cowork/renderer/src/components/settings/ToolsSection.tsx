import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'

import {
  getPrefs,
  listBuiltinTools,
  setPref,
  type BuiltinToolGroup,
} from '../../api/agent'

/** Settings → Tools — 組別 checkbox + 展開個別 tool override。
 *  Disabled tools 存 prefs `disabled_tools`(CSV),sidecar `_build_conversation`
 *  讀後傳給 build_default_tool_set 過濾。改動會清 in-memory conv cache 立刻生效。 */
export function ToolsSection() {
  const [groups, setGroups] = useState<BuiltinToolGroup[]>([])
  const [disabled, setDisabled] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      const [g, prefs] = await Promise.all([listBuiltinTools(), getPrefs()])
      setGroups(g)
      const raw = prefs.disabled_tools ?? ''
      setDisabled(new Set(raw.split(',').map((s) => s.trim()).filter(Boolean)))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function persist(next: Set<string>) {
    setSaving(true)
    try {
      const csv = Array.from(next).sort().join(',')
      await setPref('disabled_tools', csv || null)
    } finally {
      setSaving(false)
    }
  }

  function toggleTool(name: string) {
    setDisabled((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      void persist(next)
      return next
    })
  }

  function toggleGroup(g: BuiltinToolGroup) {
    const allDisabled = g.tools.every((t) => disabled.has(t.name))
    setDisabled((prev) => {
      const next = new Set(prev)
      if (allDisabled) {
        // 整組原本全 disabled → 啟用全部
        for (const t of g.tools) next.delete(t.name)
      } else {
        // 否則停用全部
        for (const t of g.tools) next.add(t.name)
      }
      void persist(next)
      return next
    })
  }

  function toggleExpand(group: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(group)) next.delete(group)
      else next.add(group)
      return next
    })
  }

  if (loading && groups.length === 0) {
    return <div className="text-sm text-fg-muted">載入工具列表…</div>
  }

  const totalDisabled = disabled.size
  const totalTools = groups.reduce((n, g) => n + g.tools.length, 0)

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-xs text-fg-subtle">
          總共 {totalTools} 個 builtin tools,目前停用 {totalDisabled} 個。
          改動會讓下次送訊息時 LLM 看到新工具列表。
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={saving}
          title="重新載入工具列表"
          className="flex items-center gap-1 rounded-md p-1.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:opacity-40"
        >
          <RefreshCw size={12} />
        </button>
      </div>
      <ul className="flex flex-col gap-1">
        {groups.map((g) => {
          const groupDisabledCount = g.tools.filter((t) => disabled.has(t.name)).length
          const allDisabled = groupDisabledCount === g.tools.length
          const someDisabled = groupDisabledCount > 0 && !allDisabled
          const isExpanded = expanded.has(g.group)
          return (
            <li
              key={g.group}
              className="rounded-lg border border-bg-hover bg-bg-panel"
            >
              <div className="flex items-center gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() => toggleExpand(g.group)}
                  className="rounded p-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
                  title={isExpanded ? '收起' : '展開個別 tool'}
                >
                  {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                <label className="flex flex-1 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    className="accent-accent"
                    checked={!allDisabled}
                    ref={(el) => {
                      if (el) el.indeterminate = someDisabled
                    }}
                    onChange={() => toggleGroup(g)}
                  />
                  <span className="text-sm font-medium text-fg-base">{g.group}</span>
                  <span className="font-mono text-[11px] text-fg-subtle">
                    {g.tools.length - groupDisabledCount}/{g.tools.length}
                  </span>
                </label>
              </div>
              {isExpanded && (
                <ul className="border-t border-bg-hover px-3 py-1">
                  {g.tools.map((t) => {
                    const off = disabled.has(t.name)
                    return (
                      <li key={t.name} className="py-1">
                        <label className="flex cursor-pointer items-start gap-2">
                          <input
                            type="checkbox"
                            className="mt-0.5 accent-accent"
                            checked={!off}
                            onChange={() => toggleTool(t.name)}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="font-mono text-xs text-fg-base">{t.name}</div>
                            <div className="truncate text-[11px] text-fg-subtle">
                              {t.description}
                            </div>
                          </div>
                        </label>
                      </li>
                    )
                  })}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
