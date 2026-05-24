import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import { useTranslation } from '../i18n'

interface Schedule {
  id: string
  name: string
  cron_expr: string
  payload: string
  enabled: boolean
}

const inputCls =
  'w-full border border-claude-border rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-claude-cream text-claude-text placeholder:text-claude-textFaint focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow'

export function SchedulesPanel() {
  const { t } = useTranslation()
  const [items, setItems] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [cron, setCron] = useState('0 9 * * *')
  const [payload, setPayload] = useState('')

  async function refresh() {
    try {
      setItems(await apiFetch<Schedule[]>('/schedules'))
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
    if (!name.trim() || !cron.trim()) return
    setError(null)
    try {
      await apiFetch('/schedules', {
        method: 'POST',
        body: {
          name: name.trim(),
          cron_expr: cron.trim(),
          trigger_type: 'prompt',
          payload,
        },
      })
      setName('')
      setPayload('')
      await refresh()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.message}` : String(e))
    }
  }

  async function remove(id: string) {
    await apiFetch(`/schedules/${id}`, { method: 'DELETE' }).catch(() => {})
    await refresh()
  }

  return (
    <div className="p-6 space-y-4 text-[14px]">
      <div>
        <div className="font-medium text-claude-text">
          {t('settings.schedules.title')}
        </div>
        <div className="text-[12px] text-claude-textDim">
          {t('settings.schedules.desc')}
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
          placeholder={t('settings.schedules.namePlaceholder')}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className={`${inputCls} font-mono`}
          placeholder="0 9 * * *"
          value={cron}
          onChange={(e) => setCron(e.target.value)}
        />
        <textarea
          className={`${inputCls} h-16 resize-none`}
          placeholder={t('settings.schedules.payloadPlaceholder')}
          value={payload}
          onChange={(e) => setPayload(e.target.value)}
        />
        <button
          onClick={() => void create()}
          disabled={!name.trim() || !cron.trim()}
          className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
        >
          {t('common.new')}
        </button>
      </div>

      {loading ? (
        <div className="text-[13px] text-claude-textDim italic">
          {t('common.loading')}
        </div>
      ) : items.length === 0 ? (
        <div className="text-[13px] text-claude-textFaint italic">
          {t('settings.schedules.empty')}
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((s) => (
            <div
              key={s.id}
              className="group flex items-center gap-3 p-3 rounded-md bg-white dark:bg-claude-panel border border-claude-borderSoft"
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium text-claude-text truncate">
                  {s.name}
                </div>
                <div className="text-[12px] text-claude-textDim font-mono truncate">
                  {s.cron_expr}
                </div>
              </div>
              <button
                className="opacity-0 group-hover:opacity-100 p-1 text-claude-textFaint hover:text-red-600 transition"
                onClick={() => void remove(s.id)}
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
