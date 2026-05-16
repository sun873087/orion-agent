import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { User, Sparkles, Info, ImageIcon, RefreshCw } from 'lucide-react'

import { loadAttachment } from '../api/agent'
import { useRegenerate } from '../hooks/useAgent'
import { useTranslation } from '../i18n'
import { useAgentStore, type AttachmentPreview, type Message } from '../store/agent'
import { ToolCallPanel } from './ToolCallPanel'

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

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <Avatar role={message.role} />
      <div className={`flex max-w-[80%] flex-col ${isUser ? 'items-end' : 'items-start'}`}>
        {/* 附件圖(只 user 訊息會帶) — 歷史 attachment 用 ref lazy load。 */}
        {!!message.attachments?.length && (
          <div className={`mb-2 flex flex-wrap gap-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
            {message.attachments.map((att, i) => (
              <LazyAttachment key={i} att={att} />
            ))}
          </div>
        )}
        {message.text && (
          <div
            className={`rounded-2xl px-4 py-2 ${
              isUser
                ? 'rounded-tr-sm bg-accent text-white'
                : 'rounded-tl-sm bg-bg-panel text-fg-base'
            }`}
          >
            {isUser ? (
              <span className="whitespace-pre-wrap">{message.text}</span>
            ) : (
              <div className="prose-orion">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.text + (message.streaming ? '​' : '')}
                </ReactMarkdown>
                {message.streaming && <span className="cursor-blink" />}
              </div>
            )}
          </div>
        )}
        {!!message.toolCalls?.length && (
          <div className="mt-2 flex w-full flex-col gap-1">
            {message.toolCalls.map((tc) => (
              <ToolCallPanel key={tc.toolUseId} toolCall={tc} />
            ))}
          </div>
        )}
        {/* Regenerate(只最後一個 assistant message 顯示)*/}
        {!isUser && isLastAssistant && !message.streaming && <RegenerateButton />}
      </div>
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
