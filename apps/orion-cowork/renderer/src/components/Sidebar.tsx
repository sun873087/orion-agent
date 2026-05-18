import { useEffect, useRef, useState } from 'react'
import {
  Check,
  ChevronRight,
  Clock,
  Loader2,
  Edit3,
  Folder,
  FolderPlus,
  Globe,
  Inbox,
  MessageSquare,
  MoreHorizontal,
  Plus,
  Search,
  Settings as SettingsIcon,
  Star,
  Trash2,
  User,
  X,
} from 'lucide-react'

import {
  getSessionWorkspace,
  renameConversation,
  searchConversations,
  setSessionProject,
  setSessionStarred,
  type SearchHit,
} from '../api/agent'
import { LOCALES, useTranslation, type Locale } from '../i18n'
import { useDeleteConversation, useNewConversation, useSwitchConversation } from '../hooks/useAgent'
import { useLoadProjectsOnce, useProjects } from '../hooks/useProjects'
import { useAgentStore, type SessionSummary } from '../store/agent'
import { useSettingsStore } from '../store/settings'

/** 左側對話列表 + 底部 user popup menu(支援 nested submenu)。 */
export function Sidebar() {
  const { t } = useTranslation()
  useLoadProjectsOnce()
  const sessions = useAgentStore((s) => s.sessions)
  const currentId = useAgentStore((s) => s.sessionId)
  const newConv = useNewConversation()
  const switchTo = useSwitchConversation()
  const del = useDeleteConversation()
  const searchOpen = useSettingsStore((s) => s.sidebarSearchOpen)
  const searchQuery = useSettingsStore((s) => s.sidebarSearchQuery)
  const setSearchQuery = useSettingsStore((s) => s.setSidebarSearchQuery)
  const toggleSearch = useSettingsStore((s) => s.toggleSidebarSearch)
  const activeProjectId = useSettingsStore((s) => s.activeProjectId)
  const [sessionExt, setSessionExt] = useState<Map<string, { project_id: string | null }>>(
    new Map(),
  )
  // 永遠 fetch ext — 個人 scope 需要過濾「不屬於任何 project」的 chat,
  // project scope 需要過濾「屬於該 project」的 chat。兩種都要 ext。
  useEffect(() => {
    let cancelled = false
    Promise.all(
      sessions.map((s) =>
        getSessionWorkspace(s.session_id).then((ext) => [s.session_id, ext] as const),
      ),
    ).then((results) => {
      if (cancelled) return
      const m = new Map<string, { project_id: string | null }>()
      for (const [sid, ext] of results) {
        m.set(sid, { project_id: ext.project_id })
      }
      setSessionExt(m)
    })
    return () => {
      cancelled = true
    }
  }, [sessions])
  const projectFilteredSessions = sessions.filter((s) => {
    const pid = sessionExt.get(s.session_id)?.project_id ?? null
    return activeProjectId ? pid === activeProjectId : pid === null
  })

  // Backend full-text search:有 query 時 debounce 300ms call sidecar;空就清空
  const baseSessions = projectFilteredSessions
  const q = searchQuery.trim()
  const [hits, setHits] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)
  useEffect(() => {
    if (!q) {
      setHits([])
      setSearching(false)
      return
    }
    setSearching(true)
    const handle = setTimeout(() => {
      let cancelled = false
      searchConversations(q)
        .then((r) => {
          if (!cancelled) setHits(r)
        })
        .catch(() => {
          if (!cancelled) setHits([])
        })
        .finally(() => {
          if (!cancelled) setSearching(false)
        })
      return () => {
        cancelled = true
      }
    }, 300)
    return () => clearTimeout(handle)
  }, [q])

  // 有 query 用 hits;空 query 用 sessions
  const showHits = q.length > 0

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-bg-hover bg-bg-panel">
      <div className="px-3 pt-3">
        <button
          type="button"
          onClick={newConv}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          <Plus size={14} />
          <span>{t('sidebar.newChat')}</span>
        </button>
      </div>
      <ProjectsSection />
      <div className="mx-3 my-2 border-t border-bg-hover" />
      {searchOpen && (
        <SearchBar
          value={searchQuery}
          onChange={setSearchQuery}
          onClose={toggleSearch}
        />
      )}
      <div className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-3">
        {showHits ? (
          searching && hits.length === 0 ? (
            <div className="px-3 py-2 text-xs text-fg-subtle">{t('sidebar.searching')}</div>
          ) : hits.length === 0 ? (
            <div className="px-3 py-2 text-xs text-fg-subtle">{t('sidebar.noMatches')}</div>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {hits.map((h) => {
                const active = h.session_id === currentId
                return (
                  <li key={h.session_id}>
                    <div
                      className={`group flex flex-col gap-0.5 rounded-md px-2 py-2 cursor-pointer ${
                        active
                          ? 'bg-bg-hover text-fg-base'
                          : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
                      }`}
                      onClick={() => switchTo(h.session_id)}
                    >
                      <div className="flex items-center gap-2">
                        <MessageSquare size={12} className="shrink-0" />
                        <span className="flex-1 truncate text-sm" title={h.title ?? h.session_id}>
                          {h.title || (
                            <span className="text-fg-subtle italic">
                              {t('sidebar.newConversation')}
                            </span>
                          )}
                        </span>
                        <span className="rounded bg-bg-input px-1 font-mono text-[10px] text-fg-subtle">
                          {h.match_count}
                        </span>
                      </div>
                      {h.snippet && (
                        <div className="line-clamp-2 pl-5 text-[11px] text-fg-subtle">
                          {h.snippet}
                        </div>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )
        ) : baseSessions.length === 0 ? (
          <div className="px-3 py-2 text-xs text-fg-subtle">{t('sidebar.empty')}</div>
        ) : (
          <SessionListGrouped
            sessions={baseSessions}
            currentId={currentId}
            onSwitch={switchTo}
            onDelete={del}
          />
        )}
      </div>

      <UserMenu />
    </aside>
  )
}

function SessionListGrouped({
  sessions,
  currentId,
  onSwitch,
  onDelete,
}: {
  sessions: SessionSummary[]
  currentId: string | null
  onSwitch: (sid: string) => void
  onDelete: (sid: string) => void
}) {
  const { t } = useTranslation()
  const starred = sessions.filter((s) => s.starred)
  const recents = sessions.filter((s) => !s.starred)

  return (
    <>
      {starred.length > 0 && (
        <div className="mb-2">
          <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">
            {t('sidebar.starred')}
          </div>
          <ul className="flex flex-col gap-0.5">
            {starred.map((s) => (
              <li key={s.session_id}>
                <SessionRow
                  sessionId={s.session_id}
                  title={s.title}
                  starred={true}
                  scheduledBy={s.scheduled_by ?? null}
                  active={s.session_id === currentId}
                  onClick={() => onSwitch(s.session_id)}
                  onDelete={() => {
                    if (window.confirm(t('sidebar.deleteConfirm'))) onDelete(s.session_id)
                  }}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
      {recents.length > 0 && (
        <div>
          {starred.length > 0 && (
            <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">
              {t('sidebar.recents')}
            </div>
          )}
          <ul className="flex flex-col gap-0.5">
            {recents.map((s) => (
              <li key={s.session_id}>
                <SessionRow
                  sessionId={s.session_id}
                  title={s.title}
                  starred={false}
                  scheduledBy={s.scheduled_by ?? null}
                  active={s.session_id === currentId}
                  onClick={() => onSwitch(s.session_id)}
                  onDelete={() => {
                    if (window.confirm(t('sidebar.deleteConfirm'))) onDelete(s.session_id)
                  }}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

function SessionRow({
  sessionId,
  title,
  starred,
  scheduledBy,
  active,
  onClick,
  onDelete,
}: {
  sessionId: string
  title: string | null
  starred: boolean
  scheduledBy: { schedule_id: string; schedule_name: string } | null
  active: boolean
  onClick: () => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  const projects = useProjects()
  const refreshSidebar = useAgentStore((s) => s.setSessions)
  // 是否這 session 還在跑(背景 streaming)— sidebar 顯轉圈圈,user 看得到
  const isRunning = useAgentStore((s) => s.busyBySession[sessionId] ?? false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [submenuOpen, setSubmenuOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title ?? '')
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!menuOpen) {
      setSubmenuOpen(false)
      return
    }
    function onDocClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    window.addEventListener('mousedown', onDocClick)
    return () => window.removeEventListener('mousedown', onDocClick)
  }, [menuOpen])

  useEffect(() => {
    if (editing) {
      setDraft(title ?? '')
      requestAnimationFrame(() => {
        inputRef.current?.focus()
        inputRef.current?.select()
      })
    }
  }, [editing, title])

  async function refresh() {
    const { listConversations } = await import('../api/agent')
    refreshSidebar(await listConversations())
  }

  async function moveTo(projectId: string | null) {
    setMenuOpen(false)
    await setSessionProject(sessionId, projectId)
    await refresh()
  }

  async function toggleStar() {
    setMenuOpen(false)
    await setSessionStarred(sessionId, !starred)
    await refresh()
  }

  async function commitRename() {
    const next = draft.trim()
    setEditing(false)
    if (!next || next === (title ?? '')) return
    await renameConversation(sessionId, next)
    await refresh()
  }

  return (
    <div
      ref={wrapRef}
      className={`group relative flex items-center gap-2 rounded-md px-2 py-2 text-sm ${
        editing ? '' : 'cursor-pointer'
      } ${
        active ? 'bg-bg-hover text-fg-base' : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
      }`}
      onClick={editing ? undefined : onClick}
    >
      {isRunning ? (
        <Loader2 size={14} className="shrink-0 animate-spin text-accent" />
      ) : starred ? (
        <Star size={14} className="shrink-0 fill-current text-warning" />
      ) : scheduledBy ? (
        <Clock size={14} className="shrink-0 text-accent" />
      ) : (
        <MessageSquare size={14} className="shrink-0" />
      )}

      {editing ? (
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename()
            else if (e.key === 'Escape') setEditing(false)
          }}
          onBlur={commitRename}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 min-w-0 rounded border border-accent/50 bg-bg-base px-1.5 py-0.5 text-sm text-fg-base focus:outline-none"
        />
      ) : (
        <span
          className="flex-1 truncate"
          title={
            scheduledBy
              ? `${title ?? sessionId} — 排程觸發:${scheduledBy.schedule_name}`
              : (title ?? sessionId)
          }
        >
          {title || (
            <span className="text-fg-subtle italic">{t('sidebar.newConversation')}</span>
          )}
        </span>
      )}

      {!editing && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setMenuOpen((o) => !o)
          }}
          title={t('sidebar.actionsTooltip')}
          className="opacity-0 group-hover:opacity-100 rounded p-1 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <MoreHorizontal size={14} />
        </button>
      )}

      {menuOpen && (
        <div
          className="absolute right-0 top-full z-20 mt-1 w-44 rounded-lg border border-bg-hover bg-bg-base p-1 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <MenuItem
            icon={<Star size={13} className={starred ? 'fill-current' : ''} />}
            label={starred ? t('sidebar.unstar') : t('sidebar.star')}
            onClick={toggleStar}
          />
          <MenuItem
            icon={<Edit3 size={13} />}
            label={t('sidebar.rename')}
            onClick={() => {
              setMenuOpen(false)
              setEditing(true)
            }}
          />
          <MenuItem
            icon={<FolderPlus size={13} />}
            label={t('sidebar.moveTo')}
            onClick={() => setSubmenuOpen((o) => !o)}
            trailing={<ChevronRight size={11} className={submenuOpen ? 'rotate-90 transition' : 'transition'} />}
          />
          {submenuOpen && (
            <div className="ml-2 border-l border-bg-hover pl-1">
              <MenuItem
                icon={<Inbox size={11} />}
                label={t('sidebar.personalConversations')}
                onClick={() => moveTo(null)}
                small
              />
              {projects.map((p) => (
                <MenuItem
                  key={p.id}
                  icon={<Folder size={11} />}
                  label={p.name}
                  onClick={() => moveTo(p.id)}
                  small
                />
              ))}
            </div>
          )}
          <div className="my-1 border-t border-bg-hover/60" />
          <MenuItem
            icon={<Trash2 size={13} />}
            label={t('sidebar.delete')}
            onClick={() => {
              setMenuOpen(false)
              onDelete()
            }}
            danger
          />
        </div>
      )}
    </div>
  )
}

function MenuItem({
  icon,
  label,
  onClick,
  danger,
  small,
  trailing,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  danger?: boolean
  small?: boolean
  trailing?: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded px-2 ${
        small ? 'py-1' : 'py-1.5'
      } text-xs ${
        danger
          ? 'text-error hover:bg-error/10'
          : 'text-fg-base hover:bg-bg-hover'
      }`}
    >
      {icon}
      <span className="flex-1 truncate text-left">{label}</span>
      {trailing}
    </button>
  )
}

function ProjectsSection() {
  const { t } = useTranslation()
  const projects = useProjects()
  const activeProjectId = useSettingsStore((s) => s.activeProjectId)
  const setActiveProjectId = useSettingsStore((s) => s.setActiveProjectId)
  const openNewProject = useSettingsStore((s) => s.openNewProject)
  const openEditProject = useSettingsStore((s) => s.openEditProject)

  return (
    <div className="mt-3 px-2">
      <div className="mb-1 flex items-center justify-between px-1">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">
          {t('sidebar.projects')}
        </span>
        <button
          type="button"
          onClick={openNewProject}
          title={t('sidebar.newProject')}
          className="rounded p-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <Plus size={12} />
        </button>
      </div>
      <ul className="flex flex-col gap-0.5">
        <li>
          <button
            type="button"
            onClick={() => setActiveProjectId(null)}
            className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm ${
              activeProjectId === null
                ? 'bg-bg-hover text-fg-base'
                : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
            }`}
          >
            <Inbox size={13} className="shrink-0" />
            <span className="flex-1 truncate text-left">{t('sidebar.personalConversations')}</span>
          </button>
        </li>
        {projects.length > 0 && (
          <li className="mx-1 my-1 border-t border-bg-hover/60" aria-hidden />
        )}
        {projects.map((p) => (
          <li key={p.id}>
            <div
              className={`group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm ${
                activeProjectId === p.id
                  ? 'bg-bg-hover text-fg-base'
                  : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
              }`}
              title={p.workspace_dir ?? undefined}
            >
              <button
                type="button"
                onClick={() => setActiveProjectId(p.id)}
                className="flex flex-1 items-center gap-2 text-left"
              >
                <Folder size={13} className="shrink-0" />
                <span className="flex-1 truncate">{p.name}</span>
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  openEditProject(p.id)
                }}
                className="opacity-0 group-hover:opacity-100 rounded p-0.5 text-fg-subtle hover:bg-bg-hover hover:text-fg-base"
                title={t('projectSettings.openSettings')}
              >
                <SettingsIcon size={11} />
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function SearchBar({
  value,
  onChange,
  onClose,
}: {
  value: string
  onChange: (v: string) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    inputRef.current?.focus()
  }, [])
  return (
    <div className="px-3 pb-2">
      <div className="flex items-center gap-1 rounded-md border border-bg-hover bg-bg-input px-2">
        <Search size={12} className="text-fg-subtle" />
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onClose()
          }}
          placeholder={t('sidebar.searchPlaceholder')}
          className="flex-1 bg-transparent py-1.5 text-xs text-fg-base placeholder:text-fg-subtle focus:outline-none"
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange('')}
            className="rounded p-0.5 text-fg-subtle hover:bg-bg-hover hover:text-fg-base"
            title={t('sidebar.clearSearch')}
          >
            <X size={11} />
          </button>
        )}
      </div>
    </div>
  )
}

type Submenu = 'language' | null

/**
 * Sidebar 左下 user button + popup menu。
 * 有些項目走 nested submenu(像 Language),有些直接 action(Settings)。
 * 加新 item 只改 buildItems() 內的 array。
 */
function UserMenu() {
  const { t } = useTranslation()
  const openSettings = useSettingsStore((s) => s.openSettings)
  const [open, setOpen] = useState(false)
  const [submenu, setSubmenu] = useState<Submenu>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        closeAll()
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (submenu) setSubmenu(null)
        else closeAll()
      }
    }
    window.addEventListener('mousedown', onMouseDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [open, submenu])

  function closeAll() {
    setOpen(false)
    setSubmenu(null)
  }

  type MenuItem =
    | { kind: 'action'; key: string; label: string; icon: JSX.Element; onClick: () => void }
    | { kind: 'submenu'; key: string; label: string; icon: JSX.Element; submenu: Submenu }

  const items: MenuItem[] = [
    {
      kind: 'action',
      key: 'settings',
      label: t('menu.settings'),
      icon: <SettingsIcon size={14} />,
      onClick: () => {
        closeAll()
        openSettings()
      },
    },
    {
      kind: 'submenu',
      key: 'language',
      label: t('menu.language'),
      icon: <Globe size={14} />,
      submenu: 'language',
    },
  ]

  return (
    <div ref={rootRef} className="relative border-t border-bg-hover p-2">
      {open && (
        <div className="absolute bottom-full left-2 right-2 mb-1 rounded-lg border border-bg-hover bg-bg-base p-1 shadow-2xl">
          {items.map((it) => {
            const isActive = it.kind === 'submenu' && submenu === it.submenu
            return (
              <div key={it.key} className="relative">
                <button
                  type="button"
                  onMouseEnter={() => {
                    if (it.kind === 'submenu') setSubmenu(it.submenu)
                    else setSubmenu(null)
                  }}
                  onClick={() => {
                    if (it.kind === 'action') it.onClick()
                    else setSubmenu(submenu === it.submenu ? null : it.submenu)
                  }}
                  className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-fg-base hover:bg-bg-hover ${
                    isActive ? 'bg-bg-hover' : ''
                  }`}
                >
                  <span className="flex items-center gap-2">
                    {it.icon}
                    <span>{it.label}</span>
                  </span>
                  {it.kind === 'submenu' && (
                    <ChevronRight size={12} className="text-fg-subtle" />
                  )}
                </button>
                {it.kind === 'submenu' && submenu === it.submenu && (
                  <LanguageSubmenu onPick={closeAll} />
                )}
              </div>
            )
          })}
        </div>
      )}
      <button
        type="button"
        onClick={() => {
          if (open) closeAll()
          else setOpen(true)
        }}
        title={t('sidebar.openMenu')}
        className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-fg-base hover:bg-bg-hover"
      >
        <UserAvatarMini />
        <span className="flex-1 truncate text-left">{t('sidebar.localUser')}</span>
      </button>
    </div>
  )
}

function UserAvatarMini() {
  const userAvatar = useSettingsStore((s) => s.userAvatar)
  if (userAvatar) {
    return (
      <div className="h-7 w-7 shrink-0 overflow-hidden rounded-full">
        <img src={userAvatar} alt="user" className="h-full w-full object-cover" />
      </div>
    )
  }
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/20 text-accent">
      <User size={14} />
    </div>
  )
}

function LanguageSubmenu({ onPick }: { onPick: () => void }) {
  const { t } = useTranslation()
  const locale = useSettingsStore((s) => s.locale)
  const setLocale = useSettingsStore((s) => s.setLocale)

  return (
    <div
      // 對齊 Language item bottom 往上 grow — popup 本身就在 sidebar 底,
      // 從 item top 往下會超出 viewport / 被 input bar 蓋住。
      className="absolute left-full bottom-0 ml-1 w-48 rounded-lg border border-bg-hover bg-bg-base p-1 shadow-2xl"
      // 子 menu 維持顯示:hover 進來不要被 parent 的 onMouseEnter 清掉
      onMouseEnter={(e) => e.stopPropagation()}
    >
      {LOCALES.map((l) => {
        const active = l === locale
        return (
          <button
            key={l}
            type="button"
            onClick={() => {
              setLocale(l)
              onPick()
            }}
            className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
              active ? 'bg-accent/15 text-accent' : 'text-fg-base hover:bg-bg-hover'
            }`}
          >
            <span className="flex items-center gap-2">
              {active ? <Check size={12} /> : <Globe size={12} className="opacity-50" />}
              <span>{t(`lang.${l}` as `lang.${Locale}`)}</span>
            </span>
            <span className="font-mono text-[10px] text-fg-subtle">{l}</span>
          </button>
        )
      })}
    </div>
  )
}
