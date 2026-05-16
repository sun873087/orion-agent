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

  // Empty state 的 hero 由 InputBox 自己顯示(對齊 Claude Cowork)。
  // 這裡只 render 訊息列;沒訊息時就讓 chat column 上方空白,InputBox 自動 fill。
  if (messages.length === 0) return null

  return (
    <div
      ref={containerRef}
      className="scrollbar-thin flex-1 overflow-y-auto px-6 py-4"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {messages.map((m, i) => (
          <MessageBubble
            key={m.id}
            message={m}
            isLastAssistant={
              m.role === 'assistant' &&
              !messages.slice(i + 1).some((later) => later.role === 'assistant')
            }
          />
        ))}
      </div>
    </div>
  )
}
