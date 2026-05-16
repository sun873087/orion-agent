import { useEffect, useRef } from 'react'

import { useAgentStore } from '../store/agent'
import { MessageBubble } from './MessageBubble'

/** 訊息列表 + 自動 scroll 到底(僅在 user 已在底時)。 */
export function MessageList() {
  const messages = useAgentStore((s) => s.messages)
  const containerRef = useRef<HTMLDivElement>(null)
  const wasAtBottomRef = useRef(true)

  // 監聽 scroll,記錄 user 是否已在底
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onScroll = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight
      wasAtBottomRef.current = dist < 50
    }
    el.addEventListener('scroll', onScroll)
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  // messages 變動時,若 user 在底就自動 follow
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    if (wasAtBottomRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-center text-fg-muted">
        <div>
          <p className="text-sm">Start a conversation</p>
          <p className="mt-1 text-xs text-fg-subtle">
            Type a prompt below — agent will respond with tools and streaming text.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="scrollbar-thin flex-1 overflow-y-auto px-6 py-4"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
      </div>
    </div>
  )
}
