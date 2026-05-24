import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Copy, Loader2, Search, Send, X } from 'lucide-react'

import { getTurnAudit, type TurnAudit } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore, type Message } from '../store/agent'

// Module-level stable empty — 避免 zustand selector inline `[]` infinite render
const EMPTY_MESSAGES: readonly Message[] = []

/**
 * 渲染單條 wire message:role + content。Content 可能是 string 或 list 含
 * tool_use / tool_result / text / image 等 block。對 tool_result 加警示色 +
 * 「送了雲端」badge — 提醒 user 這段檔案內容真的離開機器了。
 */
function WireMessageCard({
  role,
  content,
  t,
}: {
  role: string
  content: string | Array<Record<string, unknown>>
  t: (key: string) => string
}) {
  const blocks = Array.isArray(content)
    ? content
    : [{ type: 'text', text: content }]
  return (
    <li className="rounded border border-bg-hover bg-bg-panel/40 px-2 py-1.5">
      <div className="mb-1 font-mono text-[9px] uppercase text-fg-subtle">{role}</div>
      <div className="space-y-1">
        {blocks.map((block, i) => {
          const type = typeof block.type === 'string' ? block.type : 'text'
          if (type === 'tool_result') {
            const tool_use_id = typeof block.tool_use_id === 'string' ? block.tool_use_id : ''
            const isError = block.is_error === true
            const rawContent = block.content
            const text =
              typeof rawContent === 'string'
                ? rawContent
                : Array.isArray(rawContent)
                  ? rawContent
                      .map((b) =>
                        typeof b === 'object' && b !== null && typeof (b as Record<string, unknown>).text === 'string'
                          ? (b as Record<string, string>).text
                          : '',
                      )
                      .join('\n')
                  : JSON.stringify(rawContent)
            return (
              <div
                key={i}
                className={`rounded px-2 py-1 ${
                  isError
                    ? 'border border-error/30 bg-error/10'
                    : 'border border-warning/30 bg-warning/5'
                }`}
              >
                <div className="mb-0.5 flex items-center gap-1.5 text-[9px]">
                  <span className="rounded bg-warning/20 px-1 py-0.5 font-medium text-warning">
                    {t('audit.messages.toolResultBadge')}
                  </span>
                  <span className="font-mono text-fg-subtle">
                    tool_result
                    {tool_use_id && ` · ${tool_use_id.slice(0, 8)}`}
                  </span>
                  {isError && (
                    <span className="text-error">⚠ error</span>
                  )}
                </div>
                <pre className="scrollbar-thin max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-fg-base">
                  {text || '(empty)'}
                </pre>
              </div>
            )
          }
          if (type === 'tool_use') {
            const name = typeof block.name === 'string' ? block.name : 'tool'
            const input = block.input ?? {}
            return (
              <div key={i} className="rounded border border-bg-hover bg-bg-base/40 px-2 py-1">
                <div className="mb-0.5 font-mono text-[9px] text-fg-subtle">
                  tool_use · {name}
                </div>
                <pre className="scrollbar-thin max-h-20 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-fg-muted">
                  {JSON.stringify(input, null, 2)}
                </pre>
              </div>
            )
          }
          if (type === 'image') {
            return (
              <div key={i} className="text-[10px] italic text-fg-subtle">
                [image · {typeof block.media_type === 'string' ? block.media_type : 'unknown'}]
              </div>
            )
          }
          // text / thinking / tombstone 等預設純文字
          const text = typeof block.text === 'string' ? block.text : typeof block.summary === 'string' ? block.summary : ''
          return (
            <div key={i} className="whitespace-pre-wrap text-fg-base">
              {text}
            </div>
          )
        })}
      </div>
    </li>
  )
}

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
  const [copied, setCopied] = useState(false)
  // 各區段預設摺疊狀態 — system_prompt / messages 大,預設展開讓 user 直接看到
  const [showSystem, setShowSystem] = useState(true)
  const [showMessages, setShowMessages] = useState(true)
  const [showTools, setShowTools] = useState(false)
  // Fallback 用 messagesBySession,當 wire 為 null 時顯 approximate 對話內容
  const fallbackMessages = useAgentStore((s) =>
    sessionId ? s.messagesBySession[sessionId] ?? EMPTY_MESSAGES : EMPTY_MESSAGES,
  )

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

  // 切到該 turn 的 fallback messages slice — 找第 turnIndex 個 user msg 開始,
  // 直到下一個 user msg(或結尾)為止
  const fallbackSlice = useMemo(() => {
    if (turnIndex == null || turnIndex < 1) return fallbackMessages
    let userCount = 0
    let sliceEnd = fallbackMessages.length
    for (let i = 0; i < fallbackMessages.length; i++) {
      if (fallbackMessages[i].role === 'user') {
        userCount += 1
        if (userCount === turnIndex + 1) {
          sliceEnd = i
          break
        }
      }
    }
    return fallbackMessages.slice(0, sliceEnd)
  }, [fallbackMessages, turnIndex])

  async function handleCopy() {
    if (!audit) return
    const parts: string[] = []
    parts.push('=== System Prompt ===')
    parts.push(audit.systemPrompt || '(empty)')
    parts.push('')
    parts.push('=== Messages ===')
    const msgs = audit.wireMessages ?? fallbackSlice.map((m) => ({
      role: m.role,
      content: m.text,
    }))
    parts.push(JSON.stringify(msgs, null, 2))
    parts.push('')
    parts.push(`=== Model ===`)
    parts.push(`${audit.provider} / ${audit.model}`)
    parts.push(`tokens: input=${audit.inputTokens} output=${audit.outputTokens} cache_read=${audit.cacheReadTokens}`)
    parts.push(`cost: $${audit.costUsd.toFixed(6)}`)
    const text = parts.join('\n')
    // 1) 優先 navigator.clipboard;非 secure context / Electron file:// 載入會掛
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
        return
      }
    } catch {
      // fall through 走 textarea fallback
    }
    // 2) Fallback:離畫面 textarea + execCommand('copy') — Electron 一定吃
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      ta.style.pointerEvents = 'none'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (ok) {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }
    } catch {
      // 兩種都掛就放棄
    }
  }

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
          <div className="flex items-center gap-1.5">
            {audit && !loading && (
              <button
                type="button"
                onClick={handleCopy}
                className="flex items-center gap-1 rounded-md border border-bg-hover px-2 py-1 text-[11px] text-fg-muted hover:bg-bg-hover hover:text-fg-base"
                title={t('audit.copy.tooltip')}
              >
                {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
                {copied ? t('audit.copy.copied') : t('audit.copy.label')}
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
              aria-label={t('audit.close')}
            >
              <X size={16} />
            </button>
          </div>
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

              {/* Messages — 真實送 LLM 的 wire payload 或 fallback */}
              <section>
                <button
                  type="button"
                  onClick={() => setShowMessages((v) => !v)}
                  className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-fg-subtle hover:text-fg-muted"
                >
                  {showMessages ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  {t('audit.section.messages')}
                  <span className="text-[10px] normal-case text-fg-subtle">
                    ({audit.wireMessages ? audit.wireMessages.length : fallbackSlice.length})
                  </span>
                  {audit.wireMessages ? (
                    <span className="ml-2 rounded bg-info/20 px-1.5 py-0.5 text-[9px] normal-case text-info">
                      {t('audit.messages.wire')}
                    </span>
                  ) : (
                    <span className="ml-2 rounded bg-warning/20 px-1.5 py-0.5 text-[9px] normal-case text-warning">
                      {t('audit.messages.fallback')}
                    </span>
                  )}
                </button>
                {showMessages && (
                  <>
                    <p className="mb-2 text-[10px] text-fg-subtle">
                      {audit.wireMessages
                        ? t('audit.messages.wireHint')
                        : t('audit.messages.fallbackHint')}
                    </p>
                    <ul className="space-y-1.5 text-xs">
                      {audit.wireMessages ? (
                        audit.wireMessages.map((m, i) => (
                          <WireMessageCard key={i} role={m.role} content={m.content} t={t} />
                        ))
                      ) : (
                        fallbackSlice.map((m) => (
                          <li
                            key={m.id}
                            className="rounded border border-bg-hover bg-bg-panel/40 px-2 py-1.5"
                          >
                            <div className="mb-0.5 font-mono text-[9px] uppercase text-fg-subtle">
                              {m.role}
                            </div>
                            <div className="whitespace-pre-wrap text-fg-base">{m.text}</div>
                          </li>
                        ))
                      )}
                    </ul>
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
