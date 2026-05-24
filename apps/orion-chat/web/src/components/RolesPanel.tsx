import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import { useTranslation } from '../i18n'

type PermissionMode = 'ask' | 'act'

interface RoleSummary {
  name: string
  description: string
  default_disabled_tools: string[]
  default_permission_mode: PermissionMode | null
  editable: boolean
}

interface RoleDetail extends RoleSummary {
  body: string
}

const inputCls =
  'w-full border border-claude-border rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-claude-cream text-claude-text placeholder:text-claude-textFaint focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow'

export function RolesPanel() {
  const { t } = useTranslation()
  const [items, setItems] = useState<RoleSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<RoleDetail | null>(null)
  const [creating, setCreating] = useState(false)

  async function refresh() {
    setError(null)
    try {
      setItems(await apiFetch<RoleSummary[]>('/roles'))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function openItem(name: string) {
    try {
      setEditing(
        await apiFetch<RoleDetail>(`/roles/${encodeURIComponent(name)}`),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function deleteItem(name: string) {
    if (!confirm(t('settings.roles.deleteConfirm', { name }))) return
    try {
      await apiFetch(`/roles/${encodeURIComponent(name)}`, { method: 'DELETE' })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="p-6 space-y-4 text-[14px]">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-medium text-claude-text">
            {t('settings.roles.title')}
          </div>
          <div className="text-[12px] text-claude-textDim">
            {t('settings.roles.desc')}
          </div>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 bg-claude-orange hover:bg-claude-orangeHover text-white rounded-md text-[13px] font-medium transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 3v10M3 8h10"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          {t('common.new')}
        </button>
      </div>

      {error && (
        <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-[13px] text-claude-textDim italic">
          {t('common.loading')}
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((r) => (
            <div
              key={r.name}
              className={`group flex items-start gap-3 p-3 rounded-md bg-white dark:bg-claude-panel border border-claude-borderSoft transition-colors ${
                r.editable ? 'hover:border-claude-border cursor-pointer' : ''
              }`}
              onClick={r.editable ? () => void openItem(r.name) : undefined}
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium text-claude-text truncate flex items-center gap-2">
                  {r.name}
                  {!r.editable && (
                    <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-claude-borderSoft text-claude-textDim uppercase tracking-wide">
                      {t('settings.skills.readonly')}
                    </span>
                  )}
                </div>
                <div className="text-[12px] text-claude-textDim truncate">
                  {r.description}
                </div>
              </div>
              {r.editable && (
                <button
                  className="opacity-0 group-hover:opacity-100 p-1 text-claude-textFaint hover:text-red-600 transition"
                  onClick={(e) => {
                    e.stopPropagation()
                    void deleteItem(r.name)
                  }}
                  aria-label={t('common.delete')}
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path
                      d="M4 4l8 8M12 4l-8 8"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {(editing || creating) && (
        <RoleEditor
          initial={editing}
          onClose={() => {
            setEditing(null)
            setCreating(false)
          }}
          onSaved={async () => {
            setEditing(null)
            setCreating(false)
            await refresh()
          }}
        />
      )}
    </div>
  )
}

interface EditorProps {
  initial: RoleDetail | null
  onClose: () => void
  onSaved: () => void | Promise<void>
}

function RoleEditor({ initial, onClose, onSaved }: EditorProps) {
  const { t } = useTranslation()
  const isCreate = initial === null
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [body, setBody] = useState(initial?.body ?? '')
  const [disabledTools, setDisabledTools] = useState(
    (initial?.default_disabled_tools ?? []).join(', '),
  )
  const [mode, setMode] = useState<PermissionMode | ''>(
    initial?.default_permission_mode ?? '',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await apiFetch(`/roles/${encodeURIComponent(name.trim())}`, {
        method: 'PUT',
        body: {
          description,
          body,
          default_disabled_tools: disabledTools
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean),
          default_permission_mode: mode || null,
        },
      })
      await onSaved()
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${e.message} (HTTP ${e.status})`
          : e instanceof Error
            ? e.message
            : String(e),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-[2px] p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-claude-cream dark:bg-claude-panel rounded-2xl shadow-modal flex flex-col max-h-[85vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-claude-border/60">
          <div className="text-[15px] font-medium">
            {isCreate
              ? t('settings.roles.newTitle')
              : t('settings.roles.editTitle')}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-panel hover:text-claude-text transition-colors"
            aria-label={t('common.close')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M4 4l8 8M12 4l-8 8"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <div className="p-5 space-y-3 overflow-y-auto">
          <div className="space-y-1">
            <div className="text-[12px] font-medium text-claude-text flex items-baseline gap-2">
              {t('settings.skills.nameLabel')}
              <span className="text-claude-textFaint font-normal">
                {t('settings.skills.nameHint')}
              </span>
            </div>
            <input
              className={`${inputCls} font-mono`}
              placeholder="backend"
              value={name}
              disabled={!isCreate}
              autoFocus={isCreate}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[12px] font-medium text-claude-text">
              {t('settings.skills.descLabel')}
            </div>
            <input
              className={inputCls}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[12px] font-medium text-claude-text">
              {t('settings.roles.bodyLabel')}
            </div>
            <textarea
              className={`${inputCls} h-36 font-mono text-[12px] leading-relaxed resize-none`}
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[12px] font-medium text-claude-text">
              {t('settings.roles.disabledTools')}
            </div>
            <input
              className={`${inputCls} font-mono`}
              placeholder="WebSearch, Bash"
              value={disabledTools}
              onChange={(e) => setDisabledTools(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <div className="text-[12px] font-medium text-claude-text">
              {t('settings.roles.permissionMode')}
            </div>
            <select
              className={inputCls}
              value={mode}
              onChange={(e) => setMode(e.target.value as PermissionMode | '')}
            >
              <option value="">{t('settings.roles.modeDefault')}</option>
              <option value="ask">ask</option>
              <option value="act">act</option>
            </select>
          </div>
          {error && (
            <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-claude-border/60">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-[13px] text-claude-textDim hover:text-claude-text transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={() => void save()}
            disabled={busy || !name.trim()}
            className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
          >
            {busy ? t('common.saving') : t('common.save')}
          </button>
        </div>
      </div>
    </div>
  )
}
