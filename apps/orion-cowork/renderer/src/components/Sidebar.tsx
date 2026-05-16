import { Plus, Trash2, MessageSquare } from 'lucide-react'

import { useDeleteConversation, useNewConversation, useSwitchConversation } from '../hooks/useAgent'
import { useAgentStore } from '../store/agent'

/** 左側對話列表。空狀態提示 "New chat"。 */
export function Sidebar() {
  const sessions = useAgentStore((s) => s.sessions)
  const currentId = useAgentStore((s) => s.sessionId)
  const newConv = useNewConversation()
  const switchTo = useSwitchConversation()
  const del = useDeleteConversation()

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-bg-hover bg-bg-panel">
      <div className="p-3">
        <button
          type="button"
          onClick={newConv}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          <Plus size={14} />
          <span>New chat</span>
        </button>
      </div>
      <div className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-3">
        {sessions.length === 0 ? (
          <div className="px-3 py-2 text-xs text-fg-subtle">No conversations yet</div>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {sessions.map((s) => {
              const active = s.session_id === currentId
              return (
                <li key={s.session_id}>
                  <div
                    className={`group flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer ${
                      active
                        ? 'bg-bg-hover text-fg-base'
                        : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
                    }`}
                    onClick={() => switchTo(s.session_id)}
                  >
                    <MessageSquare size={14} className="shrink-0" />
                    <span className="flex-1 truncate" title={s.title ?? s.session_id}>
                      {s.title || (
                        <span className="text-fg-subtle italic">(new conversation)</span>
                      )}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (window.confirm('Delete this conversation?')) {
                          del(s.session_id)
                        }
                      }}
                      title="Delete"
                      className="opacity-0 group-hover:opacity-100 rounded p-1 text-fg-muted hover:bg-error/20 hover:text-error"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </aside>
  )
}
