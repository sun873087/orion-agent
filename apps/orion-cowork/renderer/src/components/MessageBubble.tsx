import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, ChevronDown, ChevronUp, Copy, GitBranch, User, Sparkles, Info, ImageIcon, Pencil, RefreshCw, Trash2, X as XIcon } from 'lucide-react'

import { loadAttachment } from '../api/agent'
import type { ContextBreakdown } from '../api/agent'
import { useDeleteFrom, useEditAndResend, useFork, useRegenerate } from '../hooks/useAgent'
import { useTranslation } from '../i18n'
import { useAgentStore, type AttachmentPreview, type Message } from '../store/agent'
import { useSettingsStore } from '../store/settings'
import { AskUserQuestionInline } from './AskUserQuestionInline'
import { InlineFileCards } from './RightSidebar'
import { ToolCallGroup } from './ToolCallGroup'

/**
 * 訊息泡泡。user 右側、assistant / system 左側。
 * 最後一個 assistant message 顯示 regenerate 按鈕。
 */
export function MessageBubble({
  message,
  isLastAssistant,
}: {
  message: Message
  isLastAssistant?: boolean
}) {
  if (message.role === 'system' && message.kind === 'context-report' && message.contextReport) {
    return <ContextReportCard report={message.contextReport} />
  }
  if (message.role === 'system' && message.kind === 'compact-summary') {
    const beforeTokens = message.beforeTokens ?? 0
    // < 1K 顯精確 token 數;>= 1K 用 K 縮寫 — 避免短對話顯成「~0K tokens」
    const tokensLabel =
      beforeTokens >= 1000
        ? `~${Math.round(beforeTokens / 1000)}K tokens`
        : beforeTokens > 0
          ? `~${beforeTokens} tokens`
          : null
    return (
      <div className="my-3 rounded-xl border border-bg-hover bg-bg-panel/60 px-4 py-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-fg-muted">
          <Info size={12} />
          <span>對話已壓縮</span>
          {tokensLabel && (
            <span className="font-mono text-[10px] text-fg-subtle">
              · 釋出 {tokensLabel}
            </span>
          )}
        </div>
        <div className="prose-orion text-sm text-fg-base">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
        </div>
      </div>
    )
  }
  if (message.role === 'system' || message.role === 'tool') {
    return (
      <div className="my-2 flex items-center gap-2 text-xs text-fg-muted">
        <Info size={12} />
        <span>{message.text}</span>
      </div>
    )
  }

  // user 或 assistant
  const isUser = message.role === 'user'
  // Compact 前的舊訊息 — UI 灰化、淡化,讓使用者知道「LLM 已看不到這段」,
  // 但仍 scroll 看得到原始內容。grayscale 抹掉藍色 user bubble,opacity-60
  // 讓對比降下來;hover 時恢復一些讓 user 看得清。title 提供 tooltip 解釋。
  const compactedClass = message.compacted
    ? 'opacity-60 grayscale transition-opacity hover:opacity-95'
    : ''
  const [editing, setEditing] = useState(false)
  const [forkOpen, setForkOpen] = useState(false)
  const { t } = useTranslation()
  const busy = useAgentStore((s) => (s.sessionId ? s.busyBySession[s.sessionId] ?? false : false))
  const editResend = useEditAndResend()
  const deleteFrom = useDeleteFrom()
  const fork = useFork()
  // 能編輯/刪除的條件:有 DB index、非 compacted、非 streaming 中、整體沒在跑
  const canMutate =
    typeof message.messageIndex === 'number' &&
    !message.compacted &&
    !message.streaming &&
    !busy
  // Fork 條件比 mutate 寬:不影響原 session,所以 busy 也允許;只要不是
  // compacted(壓縮過的看不到原訊息,fork 過去意義不大) + 有 DB index
  const canFork =
    typeof message.messageIndex === 'number' &&
    !message.compacted &&
    !message.streaming

  return (
    <div
      className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'} ${compactedClass}`}
      title={message.compacted ? '此訊息已被壓縮,LLM 看不到原文(只看到上方摘要)' : undefined}
    >
      <Avatar role={message.role} />
      <div className={`flex min-w-0 max-w-[85%] flex-1 flex-col ${isUser ? 'items-end' : 'items-stretch'}`}>
        {/* 附件圖(只 user 訊息會帶) — 歷史 attachment 用 ref lazy load。 */}
        {!!message.attachments?.length && (
          <div className={`mb-2 flex flex-wrap gap-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
            {message.attachments.map((att, i) => (
              <LazyAttachment key={i} att={att} />
            ))}
          </div>
        )}
        {isUser
          ? editing && typeof message.messageIndex === 'number'
            ? (
                <EditableUserBubble
                  initialText={message.text}
                  onCancel={() => setEditing(false)}
                  onSave={async (newText) => {
                    setEditing(false)
                    if (newText.trim() && newText !== message.text) {
                      await editResend(message.messageIndex!, newText)
                    }
                  }}
                />
              )
            : message.text && <UserMessageBubble text={message.text} />
          : message.blocks && message.blocks.length > 0
            ? // 新版:依 LLM emit 順序 inline render text + tool groups
              message.blocks.map((b, i) => {
                if (b.type === 'text') {
                  if (!b.text) return null
                  const isLast = i === message.blocks!.length - 1
                  return (
                    <div
                      key={i}
                      className={`rounded-2xl rounded-tl-sm bg-bg-panel px-4 py-2 text-fg-base ${
                        i === 0 ? '' : 'mt-2'
                      }`}
                    >
                      <div className="prose-orion">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {b.text + (message.streaming && isLast ? '​' : '')}
                        </ReactMarkdown>
                        {message.streaming && isLast && <span className="cursor-blink" />}
                      </div>
                    </div>
                  )
                }
                // tools block:從 toolCalls 撈對應的
                const calls = (message.toolCalls ?? []).filter((t) =>
                  b.toolUseIds.includes(t.toolUseId),
                )
                if (!calls.length) return null
                return (
                  <div key={i} className={`w-full ${i === 0 ? '' : 'mt-2'}`}>
                    <ToolCallGroup toolCalls={calls} />
                  </div>
                )
              })
            : // 舊版 fallback(歷史 hydrate / 沒 blocks):text + 底部 tools group
              <>
                {message.text && (
                  <div className="rounded-2xl rounded-tl-sm bg-bg-panel px-4 py-2 text-fg-base">
                    <div className="prose-orion">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {message.text + (message.streaming ? '​' : '')}
                      </ReactMarkdown>
                      {message.streaming && <span className="cursor-blink" />}
                    </div>
                  </div>
                )}
                {!!message.toolCalls?.length && (
                  <div className="mt-2 w-full">
                    <ToolCallGroup toolCalls={message.toolCalls} />
                  </div>
                )}
              </>}
        {/* Inline AskUserQuestion — 顯選項按鈕 / 開放題,user 答完 reply RPC。 */}
        {!isUser && <AskUserQuestionInline assistantId={message.id} />}
        {/* Inline file cards — assistant message 結尾若有 FileWrite/Edit,
            顯卡片讓 user 一鍵 open 生成的檔案。 */}
        {!isUser && !message.streaming && (
          <InlineFileCards
            toolCalls={(message.toolCalls ?? []).map((t) => ({
              toolName: t.toolName,
              input: t.input,
              status: t.status,
              text: t.text,
            }))}
            messageText={message.text}
          />
        )}
        {/* Action row(Copy + Edit + Delete + 可能 Regenerate)— streaming 中 / 編輯中不顯 */}
        {message.text && !message.streaming && !editing && (
          <div className={`mt-1 flex items-center gap-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
            <CopyButton text={message.text} />
            {isUser && canMutate && (
              <ActionButton
                icon={<Pencil size={12} />}
                label="編輯"
                onClick={() => setEditing(true)}
              />
            )}
            {canMutate && (
              <ActionButton
                icon={<Trash2 size={12} />}
                label="刪除"
                onClick={async () => {
                  if (confirm('刪除這條訊息以及之後所有對話?(無法復原)')) {
                    await deleteFrom(message.messageIndex!)
                  }
                }}
                danger
              />
            )}
            {/* Fork:從此訊息分叉新 session,原對話完全不動。modal 問 title。 */}
            {canFork && (
              <ActionButton
                icon={<GitBranch size={12} />}
                label={t('message.fork')}
                onClick={() => setForkOpen(true)}
              />
            )}
            {/* Regenerate 只在「最後一個 assistant」且未被 compact 的情況下顯示。 */}
            {!isUser && isLastAssistant && !message.compacted && <RegenerateButton />}
          </div>
        )}
      </div>
      {forkOpen && (
        <ForkPromptModal
          onCancel={() => setForkOpen(false)}
          onSubmit={async (title) => {
            setForkOpen(false)
            await fork(message.messageIndex!, title || undefined)
          }}
        />
      )}
    </div>
  )
}

/** 從某 turn 分叉的標題輸入 modal — Electron 不支援 window.prompt,改用 React state-driven dialog。
 *  Enter 送出、Esc 取消;不輸標題也可送(走 source title + "(fork)" 自動命名)。 */
function ForkPromptModal({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void
  onSubmit: (title: string) => void | Promise<void>
}) {
  const { t } = useTranslation()
  const [title, setTitle] = useState('')
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onCancel}
    >
      <div
        className="flex w-full max-w-md flex-col gap-3 rounded-2xl border border-bg-hover bg-bg-base p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <GitBranch size={14} />
          {t('message.fork')}
        </h2>
        <p className="text-xs text-fg-muted">{t('message.forkPromptTitle')}</p>
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void onSubmit(title.trim())
            } else if (e.key === 'Escape') {
              onCancel()
            }
          }}
          placeholder={t('message.forkTitlePlaceholder')}
          className="w-full rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-xs text-fg-muted hover:bg-bg-hover"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={() => void onSubmit(title.trim())}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90"
          >
            {t('message.forkConfirm')}
          </button>
        </div>
      </div>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  async function copy() {
    // 1) 優先用 navigator.clipboard API
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
        return
      }
    } catch {
      // fall through to textarea fallback
    }
    // 2) Fallback:離畫面 textarea + execCommand
    //    某些 Electron build / file:// 載入下 navigator.clipboard 不可用,
    //    或 reject 沒 user gesture(雖然是 onClick 本身就是 gesture)
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
      // 兩種都失敗就放棄,不炸
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      title={copied ? t('message.copied') : t('message.copy')}
      className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base"
    >
      {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
      <span>{copied ? t('message.copied') : t('message.copy')}</span>
    </button>
  )
}

/**
 * User message bubble — 超過 5 行就 collapse,加「展開 / 收合」鈕。
 * 用 line-clamp-5 CSS + ref 量 scrollHeight vs clientHeight 判斷有沒有截。
 */
function UserMessageBubble({ text }: { text: string }) {
  const { t } = useTranslation()
  // 短訊息不收摺;\n 多 OR char 長才考慮(避免 5 行普通問題被截斷)
  const newlineCount = (text.match(/\n/g) || []).length
  const isLong = newlineCount > 10 || text.length > 1500
  const [expanded, setExpanded] = useState(false)
  const [overflows, setOverflows] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  // 量內容是否真的超過 line-clamp 顯示區(避免 14 行 prose 算 long 但實際視覺
  // 折行後只 9 行就不該顯按鈕)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !isLong) {
      setOverflows(false)
      return
    }
    setOverflows(el.scrollHeight - el.clientHeight > 1)
  }, [text, isLong])

  return (
    <div className="rounded-2xl rounded-tr-sm bg-accent px-4 py-2 text-white">
      <span
        ref={ref}
        className={`whitespace-pre-wrap ${
          isLong && !expanded ? 'line-clamp-[10]' : 'block'
        }`}
      >
        {text}
      </span>
      {overflows && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 flex items-center gap-1 text-xs text-white/80 hover:text-white"
        >
          {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          <span>{expanded ? t('message.collapse') : t('message.expand')}</span>
        </button>
      )}
    </div>
  )
}

function ActionButton({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void | Promise<void>
  danger?: boolean
}) {
  return (
    <button
      type="button"
      onClick={() => {
        void onClick()
      }}
      title={label}
      className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-bg-hover ${
        danger ? 'hover:text-error' : 'hover:text-fg-base'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}

/** 編輯模式的 user message bubble — textarea + Save/Cancel。Enter 送出,Shift+Enter 換行。 */
function EditableUserBubble({
  initialText,
  onSave,
  onCancel,
}: {
  initialText: string
  onSave: (newText: string) => void | Promise<void>
  onCancel: () => void
}) {
  const [text, setText] = useState(initialText)
  const ref = useRef<HTMLTextAreaElement>(null)
  const composingRef = useRef(false)

  useEffect(() => {
    // 進編輯模式自動 focus + cursor 移到尾
    const el = ref.current
    if (!el) return
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 300) + 'px'
  }, [])

  function autoResize() {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 300) + 'px'
  }

  return (
    <div className="flex w-full flex-col gap-2 rounded-2xl rounded-tr-sm bg-accent/90 p-3">
      <textarea
        ref={ref}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          autoResize()
        }}
        onCompositionStart={() => { composingRef.current = true }}
        onCompositionEnd={() => { composingRef.current = false }}
        onKeyDown={(e) => {
          if (e.nativeEvent.isComposing || composingRef.current) return
          if (e.key === 'Escape') {
            e.preventDefault()
            onCancel()
            return
          }
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            void onSave(text)
          }
        }}
        rows={1}
        className="scrollbar-thin max-h-[300px] w-full resize-none bg-transparent text-sm text-white placeholder:text-white/60 focus:outline-none"
      />
      <div className="flex items-center justify-end gap-2 text-xs">
        <button
          type="button"
          onClick={onCancel}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-white/80 hover:bg-white/10 hover:text-white"
        >
          <XIcon size={12} />
          <span>取消</span>
        </button>
        <button
          type="button"
          onClick={() => void onSave(text)}
          disabled={!text.trim()}
          className="flex items-center gap-1 rounded-md bg-white/15 px-2 py-1 text-white hover:bg-white/25 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Check size={12} />
          <span>送出</span>
        </button>
      </div>
    </div>
  )
}

function RegenerateButton() {
  const { t } = useTranslation()
  const regen = useRegenerate()
  const busy = useAgentStore((s) => (s.sessionId ? s.busyBySession[s.sessionId] ?? false : false))
  return (
    <button
      type="button"
      onClick={regen}
      disabled={busy}
      title={t('message.regenerate')}
      className="mt-1 flex items-center gap-1 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base disabled:cursor-not-allowed disabled:opacity-40"
    >
      <RefreshCw size={12} />
      <span>{t('message.regenerate')}</span>
    </button>
  )
}

/**
 * 附件 lazy loader:
 *   - 若 att.previewUrl 已有(剛 send 過)→ 直接 render <img>
 *   - 否則用 att.ref 透過 conversation.attachment RPC 拿 data_url,
 *     拿到前顯灰底 placeholder。
 */
function LazyAttachment({ att }: { att: AttachmentPreview }) {
  const [url, setUrl] = useState<string | undefined>(att.previewUrl)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (url || !att.ref) return
    let cancelled = false
    const { sessionId, messageIndex, attachmentIndex } = att.ref
    loadAttachment(sessionId, messageIndex, attachmentIndex)
      .then((d) => {
        if (!cancelled) setUrl(d)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [att.ref, url])

  if (failed) {
    return (
      <div
        className="flex h-24 w-24 items-center justify-center rounded-lg border border-error/40 bg-error/5 text-error"
        title={att.filename}
      >
        <ImageIcon size={20} />
      </div>
    )
  }

  if (!url) {
    return (
      <div
        className="flex h-24 w-24 animate-pulse items-center justify-center rounded-lg border border-bg-hover bg-bg-panel"
        title={att.filename}
      >
        <ImageIcon size={20} className="text-fg-subtle" />
      </div>
    )
  }

  return (
    <a href={url} target="_blank" rel="noreferrer" title={att.filename}>
      <img
        src={url}
        alt={att.filename || 'attachment'}
        className="h-24 max-w-[160px] rounded-lg border border-bg-hover object-cover"
      />
    </a>
  )
}

/** /context 結果卡 — 全 sidecar 端本機算的 token 分配,沒打 LLM。 */
function ContextReportCard({ report }: { report: ContextBreakdown }) {
  const pct =
    report.maxContextTokens > 0
      ? (report.totalUsedTokens / report.maxContextTokens) * 100
      : 0
  return (
    <div className="my-3 rounded-xl border border-bg-hover bg-bg-panel/60 px-4 py-3">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-fg-base">
        <Info size={14} />
        <span>Context Usage</span>
      </div>
      <div className="mb-3 space-y-1 text-xs text-fg-base">
        <div>
          <span className="text-fg-muted">Model:</span>{' '}
          <span className="font-mono">{report.provider}/{report.model}</span>
        </div>
        <div>
          <span className="text-fg-muted">Tokens:</span>{' '}
          <span className="font-mono">
            {report.totalUsedTokens.toLocaleString()} /{' '}
            {report.maxContextTokens.toLocaleString()} ({pct.toFixed(1)}%)
          </span>
        </div>
      </div>
      <div className="mb-2 text-xs font-semibold text-fg-muted">
        Estimated usage by category
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-bg-hover text-left text-fg-muted">
            <th className="py-1 font-normal">Category</th>
            <th className="py-1 text-right font-normal">Tokens</th>
            <th className="py-1 text-right font-normal">Percentage</th>
          </tr>
        </thead>
        <tbody>
          {report.categories.map((c) => {
            const p =
              report.maxContextTokens > 0
                ? (c.tokens / report.maxContextTokens) * 100
                : 0
            return (
              <tr key={c.name} className="border-b border-bg-hover/40 last:border-0">
                <td className="py-1 text-fg-base">{c.name}</td>
                <td className="py-1 text-right font-mono text-fg-base">
                  {c.tokens.toLocaleString()}
                </td>
                <td className="py-1 text-right font-mono text-fg-muted">
                  {p.toFixed(1)}%
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {report.mcpToolsDetail.length > 0 && (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-fg-muted hover:text-fg-base">
            ▶ MCP Tools ({report.mcpToolsDetail.length})
          </summary>
          <table className="mt-2 w-full">
            <thead>
              <tr className="border-b border-bg-hover text-left text-fg-muted">
                <th className="py-1 font-normal">Tool</th>
                <th className="py-1 font-normal">Server</th>
                <th className="py-1 text-right font-normal">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {report.mcpToolsDetail.map((t) => (
                <tr key={t.name} className="border-b border-bg-hover/40 last:border-0">
                  <td className="py-1 font-mono text-fg-base">{t.name}</td>
                  <td className="py-1 text-fg-muted">{t.server}</td>
                  <td className="py-1 text-right font-mono text-fg-base">
                    {t.tokens.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {report.skillsDetail.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-fg-muted hover:text-fg-base">
            ▶ Skills ({report.skillsDetail.length})
          </summary>
          <table className="mt-2 w-full">
            <thead>
              <tr className="border-b border-bg-hover text-left text-fg-muted">
                <th className="py-1 font-normal">Skill</th>
                <th className="py-1 font-normal">Source</th>
                <th className="py-1 text-right font-normal">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {report.skillsDetail.map((s) => (
                <tr key={s.name} className="border-b border-bg-hover/40 last:border-0">
                  <td className="py-1 font-mono text-fg-base">{s.name}</td>
                  <td className="py-1 text-fg-muted">{s.source}</td>
                  <td className="py-1 text-right font-mono text-fg-base">
                    {s.tokens.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  )
}

function Avatar({ role }: { role: 'user' | 'assistant' }) {
  const userAvatar = useSettingsStore((s) => s.userAvatar)
  if (role === 'user' && userAvatar) {
    return (
      <div className="h-8 w-8 shrink-0 overflow-hidden rounded-full">
        <img src={userAvatar} alt="user" className="h-full w-full object-cover" />
      </div>
    )
  }
  return (
    <div
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
        role === 'user'
          ? 'bg-accent text-white'
          : 'bg-bg-panel text-fg-muted'
      }`}
    >
      {role === 'user' ? <User size={16} /> : <Sparkles size={16} />}
    </div>
  )
}
