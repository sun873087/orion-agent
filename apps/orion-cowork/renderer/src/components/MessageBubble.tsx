import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { User, Sparkles, Info } from 'lucide-react'

import type { Message } from '../store/agent'
import { ToolCallPanel } from './ToolCallPanel'

/**
 * 訊息泡泡。user 右側、assistant / system 左側。
 * Assistant 帶 streaming cursor + react-markdown 渲染。
 */
export function MessageBubble({ message }: { message: Message }) {
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
      </div>
    </div>
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
