import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, ChevronDown, ChevronUp, Copy, User, Sparkles, Info, ImageIcon, RefreshCw } from 'lucide-react'

import { loadAttachment } from '../api/agent'
import { useRegenerate } from '../hooks/useAgent'
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
  // 但仍 scroll 看得到原始內容。title attribute 在 hover 時提示。
  const compactedClass = message.compacted
    ? 'opacity-50 grayscale-[0.4] transition-opacity hover:opacity-80'
    : ''

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
          ? message.text && <UserMessageBubble text={message.text} />
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
        {/* Action row(Copy + optional Regenerate)— streaming 中不顯,避免閃 */}
        {message.text && !message.streaming && (
          <div className={`mt-1 flex items-center gap-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
            <CopyButton text={message.text} />
            {/* Regenerate 只在「最後一個 assistant」且未被 compact 的情況下顯示。
             *  Compacted 訊息 LLM context 已抽掉原 user prompt,點重新生成沒意義。 */}
            {!isUser && isLastAssistant && !message.compacted && <RegenerateButton />}
          </div>
        )}
      </div>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // 罕見:剪貼簿被拒(non-secure context 等);無提示但不炸
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
  const [expanded, setExpanded] = useState(false)
  const [overflows, setOverflows] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  // 量內容是否超過 5 行 — 用 useLayoutEffect 在 paint 前測,避免 flicker
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    // line-clamp 套上時,scrollHeight 是完整內容,clientHeight 是顯示區
    setOverflows(el.scrollHeight - el.clientHeight > 1)
  }, [text])

  return (
    <div className="rounded-2xl rounded-tr-sm bg-accent px-4 py-2 text-white">
      <span
        ref={ref}
        className={`block whitespace-pre-wrap ${
          !expanded ? 'line-clamp-5' : ''
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

function RegenerateButton() {
  const { t } = useTranslation()
  const regen = useRegenerate()
  const busy = useAgentStore((s) => s.busy)
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
