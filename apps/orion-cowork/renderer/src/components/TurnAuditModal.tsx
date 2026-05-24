import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Loader2, Search, X } from 'lucide-react'

import { getTurnAudit, type TurnAudit } from '../api/agent'
import { useTranslation } from '../i18n'

/**
 * A1「為什麼這樣回答」audit modal — 顯本 turn LLM 看到的:
 * - 用了哪個 model + token + cost(本 turn delta)
 * - 完整 system prompt(分組顯,可摺疊)
 * - 可用 tools 列表
 *
 * 對話歷史 messages 不在 modal 顯(renderer 端 main view 已有完整版),
 * 避免 redundant + modal 太肥。
 *
 * Sidecar audit cache 是 in-memory ring buffer 最近 20 turns — 重啟丟。
 * 拿不到 audit(NOT_FOUND)顯提示「audit 已過期」,user 知道為什麼空。
 */
export function TurnAuditModal({
  open,
  sessionId,
  turnIndex,
  onClose,
}: {
  open: boolean
  sessionId: string | null
  /** 對應某個 turn(renderer 從 user msg 計數算)。null = 拿最近一筆 */
  turnIndex: number | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [audit, setAudit] = useState<TurnAudit | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 各區段預設摺疊狀態 — system_prompt / tools 內容多,預設展開讓 user 直接看到
  const [showSystem, setShowSystem] = useState(true)
  const [showTools, setShowTools] = useState(false)

  // Esc 關閉
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Open 時 fetch
  useEffect(() => {
    if (!open || !sessionId) return
    let cancelled = false
    setAudit(null)
    setError(null)
    setLoading(true)
    getTurnAudit({ sessionId, turnIndex: turnIndex ?? undefined })
      .then((a) => {
        if (!cancelled) setAudit(a)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, sessionId, turnIndex])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-2xl flex-col rounded-2xl border border-bg-hover bg-bg-base shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-bg-hover px-5 py-3">
          <h2 className="flex items-center gap-2 text-base font-semibold text-fg-base">
            <Search size={16} />
            {t('audit.title')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
            aria-label={t('audit.close')}
          >
            <X size={16} />
          </button>
        </div>

        <div className="scrollbar-thin max-h-[70vh] overflow-y-auto px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-fg-muted">
              <Loader2 size={14} className="animate-spin" />
              <span>{t('audit.loading')}</span>
            </div>
          )}

          {error && !loading && (
            <div className="rounded-md border border-warning/30 bg-warning/5 px-3 py-3 text-xs text-warning">
              {t('audit.error.notFound')}
              <div className="mt-1 font-mono text-[10px] text-warning/70">{error}</div>
            </div>
          )}

          {audit && !loading && (
            <div className="space-y-5">
              {/* Model + cost */}
              <section>
                <h3 className="mb-2 text-[11px] uppercase tracking-wide text-fg-subtle">
                  {t('audit.section.model')}
                </h3>
                <div className="rounded-md border border-bg-hover bg-bg-panel/40 px-3 py-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-fg-base">
                      {audit.provider} · {audit.model}
                    </span>
                    <span className="font-mono text-xs text-accent">
                      ${audit.costUsd.toFixed(4)}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-fg-subtle">
                    <span>input: {audit.inputTokens.toLocaleString()}</span>
                    <span>output: {audit.outputTokens.toLocaleString()}</span>
                    {audit.cacheReadTokens > 0 && (
                      <span>cache hit: {audit.cacheReadTokens.toLocaleString()}</span>
                    )}
                    {audit.cacheCreationTokens > 0 && (
                      <span>cache write: {audit.cacheCreationTokens.toLocaleString()}</span>
                    )}
                  </div>
                </div>
              </section>

              {/* System prompt — 整段顯,collapsible */}
              <section>
                <button
                  type="button"
                  onClick={() => setShowSystem((v) => !v)}
                  className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-fg-subtle hover:text-fg-muted"
                >
                  {showSystem ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  {t('audit.section.system')}
                  <span className="text-[10px] normal-case text-fg-subtle">
                    ({audit.systemPrompt.length.toLocaleString()} chars)
                  </span>
                </button>
                {showSystem && (
                  <>
                    <p className="mb-2 text-[10px] text-fg-subtle">{t('audit.section.systemHint')}</p>
                    <pre className="scrollbar-thin max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-bg-hover bg-bg-panel/40 px-3 py-2 font-mono text-[11px] text-fg-base">
                      {audit.systemPrompt || `<${t('audit.empty')}>`}
                    </pre>
                  </>
                )}
              </section>

              {/* Tools 列表 */}
              <section>
                <button
                  type="button"
                  onClick={() => setShowTools((v) => !v)}
                  className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-fg-subtle hover:text-fg-muted"
                >
                  {showTools ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  {t('audit.section.tools')}
                  <span className="text-[10px] normal-case text-fg-subtle">
                    ({audit.tools.length})
                  </span>
                </button>
                {showTools && (
                  <ul className="space-y-1 text-xs">
                    {audit.tools.map((tool, i) => (
                      <li
                        key={`${tool.name}-${i}`}
                        className="rounded border border-bg-hover bg-bg-panel/40 px-2 py-1.5"
                      >
                        <span className="font-mono text-fg-base">{tool.name}</span>
                        {tool.description && (
                          <span className="ml-2 text-[10px] text-fg-subtle">
                            — {tool.description}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}
        </div>

        <div className="border-t border-bg-hover px-5 py-2.5 text-[10px] text-fg-subtle">
          {t('audit.hint')}
        </div>
      </div>
    </div>
  )
}
