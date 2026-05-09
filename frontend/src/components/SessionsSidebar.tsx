import type { SessionSummary } from '../types/events'

interface Props {
  sessions: SessionSummary[]
  currentSessionId: string | null
  username: string | null
  loading: boolean
  error: string | null
  onSelect: (sid: string) => void
  onNew: () => void
  onDelete: (sid: string) => void
  onLogout: () => void
}

export function SessionsSidebar({
  sessions,
  currentSessionId,
  username,
  loading,
  error,
  onSelect,
  onNew,
  onDelete,
  onLogout,
}: Props) {
  return (
    <aside className="w-64 bg-gray-100 border-r border-gray-200 flex flex-col">
      <div className="p-3 border-b border-gray-200 flex items-center justify-between">
        <span className="font-semibold text-sm">Orion Agent</span>
        <button
          className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700"
          onClick={onNew}
        >
          + New
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
        {loading && (
          <div className="text-xs text-gray-500">Loading sessions…</div>
        )}
        {error && (
          <div className="text-xs text-red-600 bg-red-50 p-2 rounded">
            {error}
          </div>
        )}
        {!loading && sessions.length === 0 && (
          <div className="text-xs text-gray-500 px-2">
            No sessions yet. Click "New" to start.
          </div>
        )}
        {sessions.map((s) => {
          const active = s.session_id === currentSessionId
          return (
            <div
              key={s.session_id}
              className={`group rounded px-2 py-1.5 cursor-pointer text-sm flex items-center justify-between ${
                active
                  ? 'bg-blue-100 border border-blue-300'
                  : 'hover:bg-gray-200'
              }`}
              onClick={() => onSelect(s.session_id)}
            >
              <div className="flex-1 truncate">
                <div className="font-mono text-xs text-gray-700 truncate">
                  {s.session_id.slice(0, 8)}…
                </div>
                <div className="text-xs text-gray-500">
                  {s.n_messages} msg · {s.n_turns} turn
                </div>
              </div>
              <button
                className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-600 px-1"
                onClick={(e) => {
                  e.stopPropagation()
                  if (confirm('Delete this session?')) onDelete(s.session_id)
                }}
              >
                ×
              </button>
            </div>
          )
        })}
      </div>

      <div className="p-3 border-t border-gray-200 text-xs text-gray-600 flex items-center justify-between">
        <span>👤 {username ?? '?'}</span>
        <button
          className="text-blue-600 hover:underline"
          onClick={onLogout}
        >
          Logout
        </button>
      </div>
    </aside>
  )
}
