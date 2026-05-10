import type { ModelCatalog, SessionSummary } from '../types/events'

interface Props {
  sessions: SessionSummary[]
  currentSessionId: string | null
  username: string | null
  loading: boolean
  error: string | null
  catalog: ModelCatalog | null
  onSelect: (sid: string) => void
  onNew: () => void
  onDelete: (sid: string) => void
  onLogout: () => void
  onOpenSettings: () => void
}

function shortModelLabel(
  catalog: ModelCatalog | null,
  provider: string,
  model: string,
): string {
  if (catalog) {
    const p = catalog.providers.find((p) => p.id === provider)
    const m = p?.models.find((m) => m.id === model)
    if (m) return m.label
  }
  return model
}

export function SessionsSidebar({
  sessions,
  currentSessionId,
  username,
  loading,
  error,
  catalog,
  onSelect,
  onNew,
  onDelete,
  onLogout,
  onOpenSettings,
}: Props) {
  return (
    <aside className="w-[260px] shrink-0 bg-claude-panel flex flex-col">
      <div className="px-3 pt-4 pb-2">
        <div className="flex items-center gap-2 px-2 pb-3">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-claude-orange text-white text-sm font-semibold">
            O
          </span>
          <span className="text-[15px] font-semibold tracking-tight">
            Orion
          </span>
        </div>
        <button
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium hover:bg-claude-borderSoft transition-colors"
          onClick={onNew}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 3v10M3 8h10"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          New chat
        </button>
      </div>

      <div className="px-3 pt-2 pb-1 text-[11px] uppercase tracking-wider text-claude-textFaint">
        Recents
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
        {loading && (
          <div className="px-3 py-2 text-xs text-claude-textDim">Loading…</div>
        )}
        {error && (
          <div className="mx-2 my-2 text-xs text-red-700 bg-red-50 dark:text-red-300 dark:bg-red-950/40 px-2 py-1.5 rounded-md">
            {error}
          </div>
        )}
        {!loading && sessions.length === 0 && (
          <div className="px-3 py-2 text-xs text-claude-textDim">
            No conversations yet.
          </div>
        )}
        {sessions.map((s) => {
          const active = s.session_id === currentSessionId
          const label = s.session_id.slice(0, 8)
          return (
            <div
              key={s.session_id}
              role="button"
              className={`group rounded-md px-3 py-1.5 cursor-pointer text-sm flex items-center justify-between transition-colors ${
                active
                  ? 'bg-claude-borderSoft text-claude-text'
                  : 'text-claude-text/85 hover:bg-claude-borderSoft/70'
              }`}
              onClick={() => onSelect(s.session_id)}
            >
              <div className="flex-1 min-w-0">
                <div className="truncate">
                  <span className="font-mono text-[13px]">{label}</span>
                  <span className="ml-2 text-claude-textFaint text-xs">
                    {s.n_messages} msg
                  </span>
                </div>
                <div className="text-[11px] text-claude-textFaint truncate">
                  {shortModelLabel(catalog, s.provider, s.model)}
                </div>
              </div>
              <button
                className="opacity-0 group-hover:opacity-100 text-claude-textFaint hover:text-red-600 transition-opacity"
                onClick={(e) => {
                  e.stopPropagation()
                  if (confirm('Delete this conversation?'))
                    onDelete(s.session_id)
                }}
                aria-label="delete"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path
                    d="M4 4l8 8M12 4l-8 8"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
          )
        })}
      </div>

      <div className="border-t border-claude-border/60 p-2 flex items-center gap-1">
        <div className="flex-1 flex items-center gap-2 px-2 py-1.5 text-sm text-claude-text">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-claude-orange/20 text-claude-orange text-xs font-medium">
            {(username ?? '?').charAt(0).toUpperCase()}
          </span>
          <span className="truncate">{username ?? '?'}</span>
        </div>
        <button
          onClick={onOpenSettings}
          className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-borderSoft hover:text-claude-text transition-colors"
          title="Settings"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <circle
              cx="8"
              cy="8"
              r="2"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path
              d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8L3.4 3.4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
        <button
          onClick={onLogout}
          className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-borderSoft hover:text-claude-text transition-colors"
          title="Logout"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M10 11l3-3-3-3M13 8H6M9 13H3.5A1.5 1.5 0 012 11.5v-7A1.5 1.5 0 013.5 3H9"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
    </aside>
  )
}
