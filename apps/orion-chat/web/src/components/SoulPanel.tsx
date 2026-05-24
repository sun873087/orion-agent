import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import { useTranslation } from '../i18n'

interface SoulResponse {
  content: string
}

export function SoulPanel() {
  const { t } = useTranslation()
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const r = await apiFetch<SoulResponse>('/me/soul')
        setContent(r?.content ?? '')
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const r = await apiFetch<SoulResponse>('/me/soul', {
        method: 'PUT',
        body: { content },
      })
      setContent(r?.content ?? '')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function clear() {
    if (!confirm(t('settings.soul.clearConfirm'))) return
    setBusy(true)
    setError(null)
    try {
      await apiFetch('/me/soul', { method: 'DELETE' })
      setContent('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-6 space-y-4 text-[14px]">
      <div>
        <div className="font-medium text-claude-text">
          {t('settings.soul.title')}
        </div>
        <div className="text-[12px] text-claude-textDim">
          {t('settings.soul.desc')}
        </div>
      </div>

      {error && (
        <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      <textarea
        className="w-full h-64 border border-claude-border rounded-md px-3 py-2 text-[13px] font-mono leading-relaxed bg-white dark:bg-claude-cream text-claude-text placeholder:text-claude-textFaint focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow resize-none"
        placeholder={t('settings.soul.placeholder')}
        value={content}
        disabled={loading}
        onChange={(e) => setContent(e.target.value)}
      />

      <div className="flex items-center justify-end gap-2">
        <button
          onClick={() => void clear()}
          disabled={busy || loading || !content}
          className="px-3 py-1.5 text-[13px] text-claude-textDim hover:text-red-600 disabled:text-claude-textFaint disabled:hover:text-claude-textFaint transition-colors"
        >
          {t('settings.soul.clear')}
        </button>
        <button
          onClick={() => void save()}
          disabled={busy || loading}
          className="px-4 py-1.5 bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint text-white rounded-md text-[13px] font-medium transition-colors"
        >
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </div>
  )
}
