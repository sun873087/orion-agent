import { useEffect, useState } from 'react'
import { ArrowLeft, Lock, Plus, Trash2, X } from 'lucide-react'

import {
  deleteRole,
  getRole,
  listRoles,
  writeRole,
  type Role,
  type RoleListItem,
} from '../../api/agent'
import { useDisabledRoles } from '../../hooks/usePaneRolesEnabled'
import { useTranslation } from '../../i18n'

const SOURCE_COLOR: Record<string, string> = {
  bundled: 'text-fg-muted',
  user: 'text-success',
  other: 'text-fg-subtle',
  unknown: 'text-fg-subtle',
}

// 工具名建議清單 — chips 預設 / 排在前面方便挑。其他工具仍可自由 type 進來。
const SUGGESTED_TOOLS = [
  'Edit', 'Write', 'Bash', 'NotebookEdit', 'Read', 'Grep', 'Glob',
  'WebFetch', 'WebSearch', 'TodoWrite', 'Agent', 'AskPane',
]

type SourceFilter = 'all' | 'bundled' | 'user'

export function RolesSection() {
  const { t } = useTranslation()
  const [items, setItems] = useState<RoleListItem[]>([])
  const [userDir, setUserDir] = useState('')
  const [editing, setEditing] = useState<Role | 'new' | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<SourceFilter>('all')
  const { isDisabled, setRoleEnabled } = useDisabledRoles()

  async function refresh() {
    setLoading(true)
    try {
      const items = await listRoles()
      setItems(items)
      // user_dir 直接從第一筆 user role 推斷不可靠 — 改用 sidecar 回給 list 的
      // 額外 field;listRoles 已忽略它,加 raw 抓
      try {
        const res = await fetch('') // placeholder, 真的應該從 RPC 來
        void res
      } catch {
        // ignore
      }
    } finally {
      setLoading(false)
    }
  }

  // 直接從 sidecar 抓 user_roles_dir(role.list 回的 data 內帶)
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        let dir = ''
        await window.agent.call('role.list', {}, (frame) => {
          if (frame.event === 'role_list' && frame.data) {
            const d = frame.data as { user_roles_dir?: string }
            dir = d.user_roles_dir || ''
          }
        })
        if (!cancelled) setUserDir(dir)
      } catch {
        // 忽略
      }
    })()
    return () => {
      cancelled = true
    }
  }, [editing])

  useEffect(() => {
    void refresh()
  }, [])

  async function openItem(name: string) {
    const r = await getRole(name)
    if (r) setEditing(r)
  }

  async function handleDelete(r: RoleListItem) {
    if (!r.editable) return
    if (!window.confirm(t('role.deleteConfirm', { name: r.name }))) return
    await deleteRole(r.filename)
    await refresh()
  }

  if (editing !== null) {
    return (
      <RoleEditor
        role={editing === 'new' ? null : editing}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          setEditing(null)
          await refresh()
        }}
      />
    )
  }

  const filtered = items.filter((r) => {
    if (filter === 'all') return true
    if (filter === 'bundled') return r.source === 'bundled'
    if (filter === 'user') return r.source === 'user'
    return true
  })
  const counts = {
    all: items.length,
    bundled: items.filter((r) => r.source === 'bundled').length,
    user: items.filter((r) => r.source === 'user').length,
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-xs text-fg-subtle">
          {t('role.userDirLabel')}{' '}
          <code className="font-mono text-fg-muted">{userDir}</code>
        </div>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
        >
          <Plus size={12} />
          <span>{t('role.new')}</span>
        </button>
      </div>

      <div className="flex gap-1 rounded-md bg-bg-panel p-0.5">
        <FilterTab active={filter === 'all'} onClick={() => setFilter('all')}>
          {t('role.filter.all')} ({counts.all})
        </FilterTab>
        <FilterTab active={filter === 'bundled'} onClick={() => setFilter('bundled')}>
          {t('role.filter.bundled')} ({counts.bundled})
        </FilterTab>
        <FilterTab active={filter === 'user'} onClick={() => setFilter('user')}>
          {t('role.filter.user')} ({counts.user})
        </FilterTab>
      </div>

      {loading && items.length === 0 ? (
        <div className="text-sm text-fg-muted">{t('settings.mcp.loading')}</div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border border-dashed border-bg-hover p-6 text-center text-xs text-fg-subtle">
          {t('role.empty')}
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {filtered.map((r) => {
            const off = isDisabled(r.name)
            return (
              <li
                key={r.name}
                className={`flex items-start gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-2 ${
                  off ? 'opacity-60' : ''
                }`}
              >
                <button
                  type="button"
                  onClick={() => openItem(r.name)}
                  className="flex flex-1 flex-col items-start gap-0.5 text-left"
                >
                  <div className="flex items-center gap-2">
                    <span className={`font-mono text-sm ${off ? 'line-through text-fg-muted' : 'text-fg-base'}`}>
                      {r.name}
                    </span>
                    <span
                      className={`rounded bg-bg-hover px-1.5 py-0.5 font-mono text-[10px] ${
                        SOURCE_COLOR[r.source] ?? 'text-fg-muted'
                      }`}
                    >
                      {r.source}
                    </span>
                    {!r.editable && <Lock size={10} className="text-fg-subtle" />}
                    {r.default_disabled_tools.length > 0 && (
                      <span className="text-[10px] text-fg-subtle">
                        disables {r.default_disabled_tools.length}
                      </span>
                    )}
                    {off && (
                      <span className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-amber-400">
                        {t('role.row.off')}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-fg-muted">{r.description}</span>
                </button>
                {/* per-row toggle */}
                <button
                  type="button"
                  role="switch"
                  aria-checked={!off}
                  onClick={(e) => {
                    e.stopPropagation()
                    void setRoleEnabled(r.name, off) // off=true → enable;false → disable
                  }}
                  title={off ? t('role.row.enable') : t('role.row.disable')}
                  className={`relative inline-flex h-4 w-8 shrink-0 items-center rounded-full transition-colors ${
                    off ? 'bg-bg-hover' : 'bg-accent'
                  }`}
                >
                  <span
                    className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                      off ? 'translate-x-1' : 'translate-x-4'
                    }`}
                  />
                </button>
                {r.editable && (
                  <button
                    type="button"
                    onClick={() => handleDelete(r)}
                    className="rounded p-1 text-fg-muted hover:bg-error/20 hover:text-error"
                    title={t('role.delete')}
                  >
                    <Trash2 size={12} />
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function FilterTab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2.5 py-1 text-xs transition-colors ${
        active ? 'bg-bg-base text-fg-base shadow-sm' : 'text-fg-muted hover:text-fg-base'
      }`}
    >
      {children}
    </button>
  )
}

function RoleEditor({
  role,
  onClose,
  onSaved,
}: {
  role: Role | null
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { t } = useTranslation()
  // 內建 role 仍可編,但儲存自動 clone 到 user 目錄(banner 提示)。
  // readonly 從此一律 false — 給 user 直觀體驗,不要學「同名 override」概念。
  const isBundled = role !== null && role.source === 'bundled'
  const [name, setName] = useState(role?.name ?? '')
  const [description, setDescription] = useState(role?.description ?? '')
  const [body, setBody] = useState(role?.body ?? '')
  const [disabledTools, setDisabledTools] = useState<string[]>(
    role?.default_disabled_tools ?? [],
  )
  const [permMode, setPermMode] = useState<'' | 'ask' | 'act'>(
    role?.default_permission_mode ?? '',
  )
  const [newToolInput, setNewToolInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [bundledNames, setBundledNames] = useState<Set<string>>(new Set())

  // 新增模式 fetch bundled name 清單,讓 user 知道 name 撞會覆蓋
  useEffect(() => {
    if (role !== null) return
    void (async () => {
      try {
        const items = await listRoles()
        setBundledNames(new Set(items.filter((r) => r.source === 'bundled').map((r) => r.name)))
      } catch {
        // 失敗 → 略,失去 warning 而已
      }
    })()
  }, [role])

  const isNewMode = role === null
  const willOverrideBundled = isNewMode && name.trim() && bundledNames.has(name.trim())
  const canSave = name.trim() && body.trim()

  async function handleSave() {
    if (!canSave || busy) return
    setBusy(true)
    try {
      await writeRole({
        name: name.trim(),
        description: description.trim(),
        body,
        default_disabled_tools: disabledTools,
        default_permission_mode: permMode === '' ? null : permMode,
      })
      await onSaved()
    } finally {
      setBusy(false)
    }
  }

  function addTool(tool: string) {
    const trimmed = tool.trim()
    if (!trimmed) return
    if (disabledTools.includes(trimmed)) return
    setDisabledTools([...disabledTools, trimmed])
    setNewToolInput('')
  }

  function removeTool(tool: string) {
    setDisabledTools(disabledTools.filter((t) => t !== tool))
  }

  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        onClick={onClose}
        className="flex w-fit items-center gap-1 text-xs text-fg-muted hover:text-fg-base"
      >
        <ArrowLeft size={12} />
        <span>{t('memory.backToList')}</span>
      </button>

      <div className="flex flex-col gap-3 rounded-lg border border-bg-hover bg-bg-panel p-4">
        {isBundled && (
          <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            <Lock size={12} className="mt-0.5 shrink-0" />
            <span>{t('role.editingBundled')}</span>
          </div>
        )}
        <Field label={t('role.field.name')}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. data-analyst"
            className={`w-full rounded-md border bg-bg-input px-3 py-1.5 font-mono text-sm focus:outline-none focus:ring-1 ${
              willOverrideBundled
                ? 'border-amber-500/60 focus:ring-amber-500'
                : 'border-bg-hover focus:ring-accent'
            }`}
          />
          {willOverrideBundled && (
            <span className="text-[11px] text-amber-400">
              ⚠ {t('role.warn.overrideBundled', { name: name.trim() })}
            </span>
          )}
        </Field>
        <Field label={t('role.field.description')}>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('role.field.descriptionPlaceholder')}
            className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </Field>
        <Field
          label={t('role.field.disabledTools')}
          hint={t('role.field.disabledToolsHint')}
        >
          <div className="flex min-h-[36px] flex-wrap items-center gap-1.5 rounded-md border border-bg-hover bg-bg-input p-2">
            {disabledTools.length === 0 && (
              <span className="px-1 text-xs italic text-fg-subtle">
                {t('role.field.disabledToolsEmpty')}
              </span>
            )}
            {disabledTools.map((tool) => (
              <span
                key={tool}
                className="inline-flex items-center gap-1 rounded bg-bg-hover px-2 py-0.5 font-mono text-xs"
              >
                {tool}
                <button
                  type="button"
                  onClick={() => removeTool(tool)}
                  className="text-fg-muted hover:text-error"
                >
                  <X size={10} />
                </button>
              </span>
            ))}
            <input
              value={newToolInput}
              onChange={(e) => setNewToolInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  addTool(newToolInput)
                }
              }}
              onBlur={() => addTool(newToolInput)}
              placeholder="tool name + Enter"
              className="min-w-[140px] flex-1 bg-transparent px-1 font-mono text-xs focus:outline-none"
            />
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {SUGGESTED_TOOLS.filter((t) => !disabledTools.includes(t)).map((tool) => (
              <button
                key={tool}
                type="button"
                onClick={() => addTool(tool)}
                className="rounded bg-bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-fg-muted hover:bg-bg-hover hover:text-fg-base"
              >
                + {tool}
              </button>
            ))}
          </div>
        </Field>
        <Field
          label={t('role.field.permMode')}
          hint={t('role.field.permModeHint')}
        >
          <select
            value={permMode}
            onChange={(e) => setPermMode(e.target.value as '' | 'ask' | 'act')}
            className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
          >
            <option value="">{t('role.field.permMode.default')}</option>
            <option value="ask">ask</option>
            <option value="act">act</option>
          </select>
        </Field>
        <Field label={t('role.field.body')} hint={t('role.field.bodyHint')}>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={16}
            placeholder={t('role.field.bodyPlaceholder')}
            className="w-full resize-y rounded-md border border-bg-hover bg-bg-input px-3 py-2 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </Field>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md px-3 py-1.5 text-sm text-fg-muted hover:bg-bg-hover"
          >
            {t('project.cancel')}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave || busy}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isBundled ? t('role.saveAsYours') : t('memory.save')}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-fg-muted">{label}</label>
      {children}
      {hint && <span className="text-[11px] text-fg-subtle">{hint}</span>}
    </div>
  )
}
