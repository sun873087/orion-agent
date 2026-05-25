import { useEffect, useRef, useState } from 'react'
import { useTranslation } from '../i18n'
import { useUiStore } from '../store/uiStore'
import type { ModelCatalog, SessionSummary } from '../types/events'

interface Props {
  sessions: SessionSummary[]
  currentSessionId: string | null
  username: string | null
  loading: boolean
  error: string | null
  catalog: ModelCatalog | null
  collapsed: boolean
  onToggleCollapsed: () => void
  onSelect: (sid: string) => void
  onNew: () => void
  onDelete: (sid: string) => void
  onRename: (sid: string, title: string) => void
  onToggleStar: (sid: string) => void
  onFork: (sid: string) => void
  onLogout: () => void
  onOpenSettings: () => void
}

interface UserMenuProps {
  username: string | null
  variant: 'rail' | 'expanded'
  onOpenSettings: () => void
  onLogout: () => void
}

function UserMenu({
  username,
  variant,
  onOpenSettings,
  onLogout,
}: UserMenuProps) {
  const { t } = useTranslation()
  const avatar = useUiStore((s) => s.userAvatar)
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const initial = (username ?? '?').charAt(0).toUpperCase()
  const avatarInner = avatar ? (
    <img src={avatar} alt="" className="h-full w-full object-cover" />
  ) : (
    initial
  )

  return (
    <div ref={wrapRef} className="relative">
      {variant === 'rail' ? (
        <button
          onClick={() => setOpen((v) => !v)}
          className="inline-flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-claude-orange/20 text-claude-orange text-xs font-medium hover:ring-2 hover:ring-claude-borderSoft transition"
          title={username ?? '?'}
          aria-label={t('sidebar.userMenu')}
          aria-haspopup="menu"
          aria-expanded={open}
        >
          {avatarInner}
        </button>
      ) : (
        <button
          onClick={() => setOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-claude-text hover:bg-claude-borderSoft/70 transition-colors"
          aria-haspopup="menu"
          aria-expanded={open}
        >
          <span className="inline-flex h-6 w-6 items-center justify-center overflow-hidden rounded-full bg-claude-orange/20 text-claude-orange text-xs font-medium">
            {avatarInner}
          </span>
          <span className="truncate flex-1 text-left">{username ?? '?'}</span>
        </button>
      )}

      {open && (
        <div
          role="menu"
          className={`absolute z-30 w-60 rounded-lg border border-claude-border/60 bg-claude-panel shadow-lg py-1.5 ${
            variant === 'rail'
              ? 'bottom-0 left-full ml-2'
              : 'bottom-full left-0 mb-2'
          }`}
        >
          <div className="px-3 py-2 text-[12px] text-claude-textDim truncate">
            {username ?? '?'}
          </div>
          <div className="h-px bg-claude-border/60 my-1" />
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onOpenSettings()
            }}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-claude-text hover:bg-claude-borderSoft/70 transition-colors"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            {t('sidebar.settings')}
          </button>
          <div className="h-px bg-claude-border/60 my-1" />
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onLogout()
            }}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-claude-text hover:bg-claude-borderSoft/70 transition-colors"
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
            {t('sidebar.logout')}
          </button>
        </div>
      )}
    </div>
  )
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
  collapsed,
  onToggleCollapsed,
  onSelect,
  onNew,
  onDelete,
  onRename,
  onToggleStar,
  onFork,
  onLogout,
  onOpenSettings,
}: Props) {
  const { t } = useTranslation()
  if (collapsed) {
    return (
      <aside className="w-[56px] shrink-0 bg-claude-panel flex flex-col items-center py-3 gap-1">
        <button
          onClick={onToggleCollapsed}
          className="p-2 rounded-md text-claude-textDim hover:bg-claude-borderSoft hover:text-claude-text transition-colors"
          title={t('sidebar.expand')}
          aria-label={t('sidebar.expand')}
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
            <rect
              x="2"
              y="3"
              width="12"
              height="10"
              rx="1.5"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path d="M6 3v10" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
        <button
          onClick={onNew}
          className="p-2 rounded-full text-claude-textDim hover:bg-claude-borderSoft hover:text-claude-text transition-colors"
          title={t('sidebar.newChat')}
          aria-label={t('sidebar.newChat')}
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
            <circle
              cx="8"
              cy="8"
              r="6.5"
              stroke="currentColor"
              strokeWidth="1.25"
              opacity="0.55"
            />
            <path
              d="M8 5v6M5 8h6"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>

        <div className="flex-1" />

        <UserMenu
          username={username}
          variant="rail"
          onOpenSettings={onOpenSettings}
          onLogout={onLogout}
        />
      </aside>
    )
  }
  return (
    <aside className="w-[260px] shrink-0 bg-claude-panel flex flex-col">
      <div className="px-3 pt-4 pb-2">
        <div className="flex items-center justify-between gap-2 px-2 pb-3">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-claude-orange text-white text-sm font-semibold">
              O
            </span>
            <span className="text-[15px] font-semibold tracking-tight">
              Orion
            </span>
          </div>
          <button
            onClick={onToggleCollapsed}
            className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-borderSoft hover:text-claude-text transition-colors"
            title={t('sidebar.collapse')}
            aria-label={t('sidebar.collapse')}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect
                x="2"
                y="3"
                width="12"
                height="10"
                rx="1.5"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <path d="M6 3v10" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </button>
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
          {t('sidebar.newChat')}
        </button>
      </div>

      <div className="px-3 pt-2 pb-1 text-[11px] uppercase tracking-wider text-claude-textFaint">
        {t('sidebar.recents')}
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
        {loading && (
          <div className="px-3 py-2 text-xs text-claude-textDim">
            {t('common.loading')}
          </div>
        )}
        {error && (
          <div className="mx-2 my-2 text-xs text-red-700 bg-red-50 dark:text-red-300 dark:bg-red-950/40 px-2 py-1.5 rounded-md">
            {error}
          </div>
        )}
        {!loading && sessions.length === 0 && (
          <div className="px-3 py-2 text-xs text-claude-textDim">
            {t('sidebar.noConversations')}
          </div>
        )}
        {[...sessions]
          .sort((a, b) => Number(!!b.starred) - Number(!!a.starred))
          .map((s) => {
            const active = s.session_id === currentSessionId
            const starred = !!s.starred
            const title = s.title || t('sidebar.untitled')
            return (
              <div
                key={s.session_id}
                role="button"
                className={`group rounded-md px-2 py-1.5 cursor-pointer text-sm flex items-center gap-1.5 transition-colors ${
                  active
                    ? 'bg-claude-borderSoft text-claude-text'
                    : 'text-claude-text/85 hover:bg-claude-borderSoft/70'
                }`}
                onClick={() => onSelect(s.session_id)}
              >
                <button
                  className={`shrink-0 transition-opacity ${
                    starred
                      ? 'text-amber-500'
                      : 'text-claude-textFaint opacity-0 group-hover:opacity-100'
                  }`}
                  onClick={(e) => {
                    e.stopPropagation()
                    onToggleStar(s.session_id)
                  }}
                  aria-label={starred ? t('sidebar.unstar') : t('sidebar.star')}
                >
                  <svg width="13" height="13" viewBox="0 0 16 16">
                    <path
                      d="M8 1.6l1.9 3.85 4.25.62-3.07 3 .72 4.23L8 11.3 4.17 13.3l.72-4.23-3.07-3 4.25-.62L8 1.6z"
                      fill={starred ? 'currentColor' : 'none'}
                      stroke="currentColor"
                      strokeWidth="1.2"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                <div className="flex-1 min-w-0">
                  <div className="truncate">{title}</div>
                  <div className="text-[11px] text-claude-textFaint truncate">
                    {t('sidebar.msgCount', { n: s.n_messages })} ·{' '}
                    {shortModelLabel(catalog, s.provider, s.model)}
                  </div>
                </div>
                <button
                  className="shrink-0 opacity-0 group-hover:opacity-100 text-claude-textFaint hover:text-claude-text transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation()
                    const next = prompt(
                      t('sidebar.renamePrompt'),
                      s.title || '',
                    )
                    if (next && next.trim()) onRename(s.session_id, next.trim())
                  }}
                  aria-label={t('sidebar.rename')}
                >
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                    <path
                      d="M11.3 2.2l2.5 2.5L6 12.5l-3 .5.5-3 7.8-7.8z"
                      stroke="currentColor"
                      strokeWidth="1.3"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                <button
                  className="shrink-0 opacity-0 group-hover:opacity-100 text-claude-textFaint hover:text-claude-text transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation()
                    onFork(s.session_id)
                  }}
                  aria-label={t('sidebar.branch')}
                >
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                    <path
                      d="M4.5 2.5v7m0 0a1.5 1.5 0 100 3 1.5 1.5 0 000-3zm0-7a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm7 0a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm0 3c0 3-3.5 2.5-7 4"
                      stroke="currentColor"
                      strokeWidth="1.3"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
                <button
                  className="shrink-0 opacity-0 group-hover:opacity-100 text-claude-textFaint hover:text-red-600 transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (confirm(t('sidebar.deleteConfirm')))
                      onDelete(s.session_id)
                  }}
                  aria-label={t('common.delete')}
                >
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
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

      <div className="border-t border-claude-border/60 p-2">
        <UserMenu
          username={username}
          variant="expanded"
          onOpenSettings={onOpenSettings}
          onLogout={onLogout}
        />
      </div>
    </aside>
  )
}
