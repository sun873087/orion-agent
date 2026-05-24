import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import { useTranslation } from '../i18n'

interface Project {
  id: string
  name: string
  description: string | null
  custom_instructions: string | null
}

const inputCls =
  'w-full border border-claude-border rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-claude-cream text-claude-text placeholder:text-claude-textFaint focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow'

export function ProjectsPanel() {
  const { t } = useTranslation()
  const [items, setItems] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [instructions, setInstructions] = useState('')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    setError(null)
    try {
      setItems(await apiFetch<Project[]>('/projects'))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function create() {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      await apiFetch('/projects', {
        method: 'POST',
        body: { name: name.trim(), custom_instructions: instructions || null },
      })
      setName('')
      setInstructions('')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string) {
    if (!confirm(t('settings.projects.deleteConfirm'))) return
    await apiFetch(`/projects/${id}`, { method: 'DELETE' }).catch(() => {})
    await refresh()
  }

  return (
    <div className="p-6 space-y-4 text-[14px]">
      <div>
        <div className="font-medium text-claude-text">
          {t('settings.projects.title')}
        </div>
        <div className="text-[12px] text-claude-textDim">
          {t('settings.projects.desc')}
        </div>
      </div>

      {error && (
        <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      <div className="space-y-2 p-3 rounded-md border border-claude-borderSoft">
        <input
          className={inputCls}
          placeholder={t('settings.projects.namePlaceholder')}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <textarea
          className={`${inputCls} h-20 resize-none`}
          placeholder={t('settings.projects.instructionsPlaceholder')}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
        <button
          onClick={() => void create()}
          disabled={busy || !name.trim()}
          className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
        >
          {busy ? t('common.saving') : t('common.new')}
        </button>
      </div>

      {loading ? (
        <div className="text-[13px] text-claude-textDim italic">
          {t('common.loading')}
        </div>
      ) : items.length === 0 ? (
        <div className="text-[13px] text-claude-textFaint italic">
          {t('settings.projects.empty')}
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((p) => (
            <div
              key={p.id}
              className="group flex items-start gap-3 p-3 rounded-md bg-white dark:bg-claude-panel border border-claude-borderSoft"
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium text-claude-text truncate">
                  {p.name}
                </div>
                {p.custom_instructions && (
                  <div className="text-[12px] text-claude-textDim truncate">
                    {p.custom_instructions}
                  </div>
                )}
              </div>
              <button
                className="opacity-0 group-hover:opacity-100 p-1 text-claude-textFaint hover:text-red-600 transition"
                onClick={() => void remove(p.id)}
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
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
