import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Heart, Loader2, RefreshCw, Trash2 } from 'lucide-react'

import { clearSoul, getSoul, updateSoul } from '../../api/agent'
import { useTranslation } from '../../i18n'
import { useAgentStore } from '../../store/agent'
import { useSettingsStore } from '../../store/settings'

/**
 * 「Orion 對你的認識」 — soul.md 編輯 + 自動更新 toggle + 立即更新 / 清空。
 *
 * 概念取自 [soul.md](https://soul.md/):AI 的第一人稱 reflection,跨對話
 * 保持「人格延續性」。Orion 開新對話自動帶 soul 進 system_prompt,讓 LLM
 * 像認識久的朋友開口。
 *
 * Cost-conscious:預設 OFF,即使開了也只每 10 turn 更新一次。User 可手動觸
 * 發或編輯內容(因為 Orion 寫的可能有誤,user 有最終決定權)。
 */
export function SoulSection() {
  const { t, locale } = useTranslation()
  const sessionId = useAgentStore((s) => s.sessionId)
  const summaryProvider = useSettingsStore((s) => s.compactSummaryProvider)
  const summaryModel = useSettingsStore((s) => s.compactSummaryModel)
  const autoUpdate = useSettingsStore((s) => s.soulAutoUpdateEnabled)
  const setAutoUpdate = useSettingsStore((s) => s.setSoulAutoUpdateEnabled)

  const [content, setContent] = useState('')
  const [updating, setUpdating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewMode, setPreviewMode] = useState(true)

  async function load() {
    try {
      const c = await getSoul()
      setContent(c)
    } catch {
      // 拿不到不阻塞 UI(可能 sidecar 還沒起來)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function handleUpdate() {
    if (!sessionId) {
      setError(t('soul.errors.noSession'))
      return
    }
    setError(null)
    setUpdating(true)
    try {
      const fresh = await updateSoul({
        sessionId,
        summaryProvider,
        summaryModel,
        locale,
      })
      setContent(fresh)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUpdating(false)
    }
  }

  async function handleClear() {
    if (!window.confirm(t('soul.clearConfirm'))) return
    await clearSoul()
    setContent('')
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h2 className="flex items-center gap-2 text-xl font-semibold text-fg-base">
          <Heart size={18} className="text-accent" />
          {t('settings.section.soul')}
        </h2>
        <p className="text-sm text-fg-muted">{t('soul.intro')}</p>
      </header>

      {/* 自動更新 toggle */}
      <section className="space-y-2">
        <h3 className="text-sm font-medium text-fg-muted">{t('soul.autoUpdate.title')}</h3>
        <p className="text-[11px] text-fg-subtle">{t('soul.autoUpdate.desc')}</p>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-1.5 text-sm hover:border-accent/40 hover:bg-bg-hover">
          <input
            type="checkbox"
            className="accent-accent"
            checked={autoUpdate}
            onChange={(e) => setAutoUpdate(e.target.checked)}
          />
          <span>{t('soul.autoUpdate.label')}</span>
        </label>
      </section>

      {/* Soul 內容 + 操作 */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-fg-muted">{t('soul.content.title')}</h3>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleUpdate}
              disabled={updating || !sessionId}
              className="flex items-center gap-1.5 rounded-md bg-accent/15 px-3 py-1 text-xs text-accent hover:bg-accent/25 disabled:cursor-not-allowed disabled:opacity-50"
              title={!sessionId ? t('soul.errors.noSession') : undefined}
            >
              {updating ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <RefreshCw size={12} />
              )}
              {updating ? t('soul.updating') : t('soul.updateNow')}
            </button>
            {content && (
              <button
                type="button"
                onClick={handleClear}
                className="flex items-center gap-1.5 rounded-md border border-bg-hover px-3 py-1 text-xs text-fg-muted hover:border-error/40 hover:bg-error/10 hover:text-error"
              >
                <Trash2 size={12} />
                {t('soul.clear')}
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-xs text-error">
            {error}
          </div>
        )}

        {/* Preview / raw toggle */}
        {content && (
          <div className="flex items-center gap-2 text-[11px] text-fg-subtle">
            <button
              type="button"
              onClick={() => setPreviewMode(true)}
              className={`rounded px-2 py-0.5 ${previewMode ? 'bg-bg-hover text-fg-base' : 'hover:bg-bg-hover'}`}
            >
              {t('soul.preview')}
            </button>
            <button
              type="button"
              onClick={() => setPreviewMode(false)}
              className={`rounded px-2 py-0.5 ${!previewMode ? 'bg-bg-hover text-fg-base' : 'hover:bg-bg-hover'}`}
            >
              {t('soul.raw')}
            </button>
          </div>
        )}

        {!content && (
          <div className="rounded-md border border-bg-hover bg-bg-panel/40 px-4 py-6 text-center text-xs text-fg-subtle">
            {t('soul.content.empty')}
          </div>
        )}
        {content && previewMode && (
          <div className="prose-orion rounded-md border border-bg-hover bg-bg-panel/40 px-4 py-3 text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        )}
        {content && !previewMode && (
          <pre className="scrollbar-thin max-h-96 overflow-auto rounded-md border border-bg-hover bg-bg-panel/40 px-4 py-3 font-mono text-[11px] text-fg-base whitespace-pre-wrap">
            {content}
          </pre>
        )}
      </section>
    </div>
  )
}
