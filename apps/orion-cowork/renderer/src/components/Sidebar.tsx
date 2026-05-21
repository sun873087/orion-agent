import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  CheckSquare,
  ChevronRight,
  Clock,
  GitBranch,
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
  Square,
  Star,
  Trash2,
  User,
  Users,
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
  const tab = useSettingsStore((s) => s.sidebarNavTab)
  const currentCollabId = useAgentStore((s) => s.currentCollaborationId)
  const [sessionExt, setSessionExt] = useState<
    Map<string, { project_id: string | null; collaboration_id: string | null }>
  >(new Map())
  // 永遠 fetch ext — 三個 tab 都要不同 filter(personal / project / collab),
  // 故每個 session 的 project_id + collaboration_id 都要拉。
  useEffect(() => {
    let cancelled = false
    Promise.all(
      sessions.map((s) =>
        getSessionWorkspace(s.session_id).then((ext) => [s.session_id, ext] as const),
      ),
    ).then((results) => {
      if (cancelled) return
      const m = new Map<
        string,
        { project_id: string | null; collaboration_id: string | null }
      >()
      for (const [sid, ext] of results) {
        m.set(sid, {
          project_id: ext.project_id,
          collaboration_id: ext.collaboration_id,
        })
      }
      setSessionExt(m)
    })
    return () => {
      cancelled = true
    }
  }, [sessions])
  // Tab-aware filter:
  //   chats → 沒綁 project 也沒綁 collab 的純個人對話
  //   projects → 綁 project 的 session;若選了 activeProjectId,僅那個 project
  //   collaborations → 綁 collab 的 session;若開了 currentCollabId,僅那個 collab
  const projectFilteredSessions = sessions.filter((s) => {
    const ext = sessionExt.get(s.session_id)
    const pid = ext?.project_id ?? null
    const cid = ext?.collaboration_id ?? null
    if (tab === 'chats') {
      return pid === null && cid === null
    }
    if (tab === 'projects') {
      if (!pid) return false
      return activeProjectId ? pid === activeProjectId : true
    }
    // collaborations
    if (!cid) return false
    return currentCollabId ? cid === currentCollabId : true
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
      <SidebarNavTabs />
      <div className="mx-3 my-2 border-t border-bg-hover" />
      {searchOpen && (
        <SearchBar
          value={searchQuery}
          onChange={setSearchQuery}
          onClose={toggleSearch}
        />
      )}
      <SelectionToolbar visibleSessions={baseSessions} />

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

/** 多選模式 toolbar— 入口 + 全選 / 取消 / 批次刪 toolbar。
 * visibleSessions 是當前 sidebar 看得到的 session(已過 project filter)— 全選
 * 只選這些,不會誤選別 project 的。 */
function SelectionToolbar({ visibleSessions }: { visibleSessions: SessionSummary[] }) {
  const { t } = useTranslation()
  const mode = useAgentStore((s) => s.sidebarSelectionMode)
  const selected = useAgentStore((s) => s.selectedSessionIds)
  const enter = useAgentStore((s) => s.enterSidebarSelection)
  const exit = useAgentStore((s) => s.exitSidebarSelection)
  const selectAll = useAgentStore((s) => s.selectAllSessions)
  const refreshSidebar = useAgentStore((s) => s.setSessions)

  const visibleIds = useMemo(
    () => visibleSessions.map((s) => s.session_id),
    [visibleSessions],
  )
  const allSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.includes(id))

  async function doBulkDelete() {
    if (selected.length === 0) return
    // 先 async 撈 fork 子孫總數,confirm 訊息提示
    const { countForkDescendants, deleteConversations, listConversations } = await import(
      '../api/agent'
    )
    let extra = 0
    try {
      const counts = await Promise.all(selected.map(countForkDescendants))
      extra = counts.reduce((a, b) => a + b, 0)
    } catch {
      // ignore
    }
    const msg =
      extra > 0
        ? t('sidebar.bulkDeleteConfirmWithForks', {
            count: selected.length,
            total: selected.length + extra,
          })
        : t('sidebar.bulkDeleteConfirm', { count: selected.length })
    if (!window.confirm(msg)) return
    try {
      await deleteConversations(selected)
    } catch (e) {
      const err = e instanceof Error ? e.message : String(e)
      window.alert(`刪除失敗:${err}`)
    }
    exit()
    refreshSidebar(await listConversations())
  }

  if (!mode) {
    return (
      <div className="px-3 pb-1">
        <button
          type="button"
          onClick={enter}
          className="flex w-full items-center justify-center gap-1.5 rounded-md border border-bg-hover px-2 py-1 text-[11px] text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <CheckSquare size={12} />
          <span>{t('sidebar.selectMultiple')}</span>
        </button>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1 border-b border-bg-hover bg-bg-hover/30 px-3 py-2">
      <div className="flex items-center justify-between text-[11px]">
        <span className="font-mono text-fg-base">
          {t('sidebar.selectedCount', { count: selected.length })}
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => (allSelected ? selectAll([]) : selectAll(visibleIds))}
            className="rounded px-2 py-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            {allSelected ? t('sidebar.deselectAll') : t('sidebar.selectAll')}
          </button>
          <button
            type="button"
            onClick={exit}
            className="rounded px-2 py-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            {t('common.cancel')}
          </button>
        </div>
      </div>
      <button
        type="button"
        onClick={() => void doBulkDelete()}
        disabled={selected.length === 0}
        className="flex items-center justify-center gap-1.5 rounded-md bg-error/15 px-2 py-1 text-[11px] text-error hover:bg-error/25 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Trash2 size={12} />
        <span>{t('sidebar.deleteSelected', { count: selected.length })}</span>
      </button>
    </div>
  )
}

/** Fork tree 一個節點;render 時用深度優先 + depth 縮排,看起來像 Git tree。 */
type SessionTreeNode = {
  session: SessionSummary
  depth: number
  /** 是否有 children — row 顯 chevron toggle 的依據。 */
  hasChildren: boolean
  /** 是否已被 user 摺起(在 collapsed set 內)— row 決定 chevron 方向。 */
  collapsed: boolean
}

/** 從平的 session list 建 fork tree。
 *
 * - 沒 `forked_from_session_id` 的 session → root(depth 0)
 * - 有 `forked_from_session_id` 且 parent 還在 → child(depth = parent.depth + 1)
 * - 有 `forked_from_session_id` 但 parent 已刪(orphan)→ 當 root 處理
 *
 * `collapsed` Set 內的 parent 不展開 children(整棵子樹略過)— UX 跟 VS Code
 * file tree 一致。`hasChildren` 仍照原 tree 標,確保 chevron 顯示。
 *
 * 排序:root 順序保留 list_sessions 原序(最近活動 desc);children 依
 * 各自的 created_at desc(也就是 list 內出現順序)排,讓「同 parent 下的
 * fork」按建立先後一致呈現。深度優先 flatten 出最終要 render 的 row 序列。
 */
function buildSessionTree(
  sessions: SessionSummary[],
  collapsed: Set<string>,
): SessionTreeNode[] {
  const byId = new Map<string, SessionSummary>(
    sessions.map((s) => [s.session_id, s]),
  )
  // parent → children(保留 list 順序)
  const childrenMap = new Map<string, SessionSummary[]>()
  const roots: SessionSummary[] = []
  for (const s of sessions) {
    const pid = s.forked_from_session_id
    if (pid && byId.has(pid)) {
      const list = childrenMap.get(pid) ?? []
      list.push(s)
      childrenMap.set(pid, list)
    } else {
      // 沒 parent 或 orphan(parent 被刪了)當 root
      roots.push(s)
    }
  }
  // DFS flatten
  const out: SessionTreeNode[] = []
  const visited = new Set<string>()
  function walk(s: SessionSummary, depth: number): void {
    if (visited.has(s.session_id)) return // 防止 cyclic ref
    visited.add(s.session_id)
    const kids = childrenMap.get(s.session_id) ?? []
    const isCollapsed = collapsed.has(s.session_id)
    out.push({
      session: s,
      depth,
      hasChildren: kids.length > 0,
      collapsed: isCollapsed,
    })
    if (!isCollapsed) {
      for (const k of kids) walk(k, depth + 1)
    }
  }
  for (const r of roots) walk(r, 0)
  return out
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
  // Fork tree 只在 recents 段建,starred 維持平的(starred 一般 user 自己挑,
  // 樹狀關係意義不大;且 starred 通常少,不必為它做 tree)
  const collapsedList = useSettingsStore((s) => s.collapsedForkParents)
  const toggleCollapse = useSettingsStore((s) => s.toggleForkCollapse)
  const collapsedSet = useMemo(() => new Set(collapsedList), [collapsedList])
  const tree = useMemo(
    () => buildSessionTree(recents, collapsedSet),
    [recents, collapsedSet],
  )
  // 給每個 session 算 parent title,fork badge tooltip 用
  const titleById = useMemo(() => {
    const m: Record<string, string | null> = {}
    for (const s of sessions) m[s.session_id] = s.title
    return m
  }, [sessions])

  // 刪除確認:先 async 撈 fork 子孫數,confirm 訊息加 warning 提示一併刪除
  async function confirmAndDelete(sid: string): Promise<void> {
    const { countForkDescendants } = await import('../api/agent')
    let count = 0
    try {
      count = await countForkDescendants(sid)
    } catch {
      // 撈失敗就 fallback 用普通 confirm
    }
    const msg =
      count > 0
        ? `${t('sidebar.deleteConfirm')}\n\n${t('sidebar.deleteForkWarning', { count })}`
        : t('sidebar.deleteConfirm')
    if (window.confirm(msg)) onDelete(sid)
  }

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
                  depth={0}
                  hasChildren={false}
                  collapsed={false}
                  onToggleCollapse={() => {}}
                  forkedFrom={null}
                  onClick={() => onSwitch(s.session_id)}
                  onDelete={() => {
                    void confirmAndDelete(s.session_id)
                  }}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
      {tree.length > 0 && (
        <div>
          {starred.length > 0 && (
            <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">
              {t('sidebar.recents')}
            </div>
          )}
          <ul className="flex flex-col gap-0.5">
            {tree.map(({ session: s, depth, hasChildren, collapsed }) => {
              const fromSid = s.forked_from_session_id ?? null
              const fromIdx = s.forked_from_message_index ?? null
              const fromTitle = fromSid ? titleById[fromSid] ?? null : null
              return (
                <li key={s.session_id}>
                  <SessionRow
                    sessionId={s.session_id}
                    title={s.title}
                    starred={false}
                    scheduledBy={s.scheduled_by ?? null}
                    active={s.session_id === currentId}
                    depth={depth}
                    hasChildren={hasChildren}
                    collapsed={collapsed}
                    onToggleCollapse={() => toggleCollapse(s.session_id)}
                    forkedFrom={
                      fromSid
                        ? {
                            sessionId: fromSid,
                            messageIndex: fromIdx,
                            sourceTitle: fromTitle,
                          }
                        : null
                    }
                    onClick={() => onSwitch(s.session_id)}
                    onDelete={() => {
                      void confirmAndDelete(s.session_id)
                    }}
                  />
                </li>
              )
            })}
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
  depth,
  hasChildren,
  collapsed,
  onToggleCollapse,
  forkedFrom,
  onClick,
  onDelete,
}: {
  sessionId: string
  title: string | null
  starred: boolean
  scheduledBy: { schedule_id: string; schedule_name: string } | null
  active: boolean
  /** Fork tree 深度;0 = root,>0 = 縮排顯為 child。 */
  depth: number
  /** 有 fork 子節點 → 顯 chevron toggle 讓 user 摺/展(改)。 */
  hasChildren: boolean
  /** 當前是否被摺起;chevron 方向跟 children 是否在 tree flatten 中由此控。 */
  collapsed: boolean
  onToggleCollapse: () => void
  /** 非 null 時表示這 session 是 fork 來的 — 顯 GitBranch icon + tooltip。 */
  forkedFrom: {
    sessionId: string
    messageIndex: number | null
    sourceTitle: string | null
  } | null
  onClick: () => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  const projects = useProjects()
  const refreshSidebar = useAgentStore((s) => s.setSessions)
  // 是否這 session 還在跑(背景 streaming)— sidebar 顯轉圈圈,user 看得到
  const isRunning = useAgentStore((s) => s.busyBySession[sessionId] ?? false)
  // 多選模式狀態:mode on 時 row 顯 checkbox 取代 icon,點 row toggle 選取
  const selectionMode = useAgentStore((s) => s.sidebarSelectionMode)
  const selected = useAgentStore((s) => s.selectedSessionIds.includes(sessionId))
  const toggleSelected = useAgentStore((s) => s.toggleSessionSelected)
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

  // Fork tree 縮排:每層多 12px;同時顯左側淡 border 標示「同 parent」血緣帶
  const indentStyle = depth > 0
    ? { paddingLeft: `${0.5 + depth * 0.75}rem` }
    : undefined
  // Fork tooltip:顯「分叉自 <source title> 第 N 輪」
  const forkTooltip = forkedFrom
    ? t('sidebar.forkedFromTooltip', {
        title: forkedFrom.sourceTitle ?? t('sidebar.untitledSession'),
        turn: forkedFrom.messageIndex != null ? forkedFrom.messageIndex + 1 : '?',
      })
    : undefined

  // Selection mode 時 row click 改 toggle 選取(不切 session);active 視覺改為「已選」
  const rowOnClick = editing
    ? undefined
    : selectionMode
      ? () => toggleSelected(sessionId)
      : onClick
  const rowActiveClass = selectionMode
    ? selected
      ? 'bg-accent/15 text-fg-base'
      : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
    : active
      ? 'bg-bg-hover text-fg-base'
      : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'

  return (
    <div
      ref={wrapRef}
      className={`group relative flex items-center gap-2 rounded-md px-2 py-2 text-sm ${
        editing ? '' : 'cursor-pointer'
      } ${rowActiveClass} ${depth > 0 ? 'border-l-2 border-bg-hover' : ''}`}
      style={indentStyle}
      onClick={rowOnClick}
      title={forkTooltip}
    >
      {/* Selection mode 時最左顯 checkbox,取代 chevron 位置 */}
      {selectionMode ? (
        <span className="shrink-0 text-fg-muted">
          {selected ? (
            <CheckSquare size={14} className="text-accent" />
          ) : (
            <Square size={14} />
          )}
        </span>
      ) : null}
      {/* Chevron toggle:有 children 才顯;點擊只摺/展,不切 session。沒
          children 用 spacer 同寬 12px 保持其他 row 的 icon 對齊。Selection
          mode 時 chevron 仍要可用(摺/展不該被禁) */}
      {hasChildren ? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onToggleCollapse()
          }}
          className="shrink-0 rounded p-0.5 text-fg-subtle hover:bg-bg-hover hover:text-fg-base"
          title={collapsed ? t('sidebar.expandFork') : t('sidebar.collapseFork')}
        >
          <ChevronRight
            size={12}
            className={`transition-transform ${collapsed ? '' : 'rotate-90'}`}
          />
        </button>
      ) : (
        <span className="inline-block w-[16px] shrink-0" />
      )}
      {isRunning ? (
        <Loader2 size={14} className="shrink-0 animate-spin text-accent" />
      ) : starred ? (
        <Star size={14} className="shrink-0 fill-current text-warning" />
      ) : scheduledBy ? (
        <Clock size={14} className="shrink-0 text-accent" />
      ) : forkedFrom ? (
        <GitBranch size={14} className="shrink-0 text-accent/70" />
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

/** Sidebar 主 nav:[對話] [專案] [協作] 三 tab 切換,只渲染一個 section。 */
function SidebarNavTabs() {
  const { t } = useTranslation()
  const tab = useSettingsStore((s) => s.sidebarNavTab)
  const setTab = useSettingsStore((s) => s.setSidebarNavTab)
  const setActiveProjectId = useSettingsStore((s) => s.setActiveProjectId)
  const inCollab = useAgentStore((s) => s.currentCollaborationId !== null)
  const openCollaboration = useAgentStore((s) => s.openCollaboration)

  function switchTo(next: 'chats' | 'projects' | 'collaborations') {
    // 切「對話」= 個人對話 mode(no project,no collab)
    if (next === 'chats') {
      setActiveProjectId(null)
      if (inCollab) openCollaboration(null)
    }
    // 切「專案」= 關 collab,project 選擇由 user 在 section 內 click 決定
    if (next === 'projects' && inCollab) {
      openCollaboration(null)
    }
    // 切「協作」不動 project state(它被 collab view 覆蓋掉)
    setTab(next)
  }

  return (
    <>
      <div className="mt-3 flex gap-1 border-b border-bg-hover px-3">
        <TabButton
          active={tab === 'chats'}
          onClick={() => switchTo('chats')}
          label={t('sidebar.tabs.chats')}
        />
        <TabButton
          active={tab === 'projects'}
          onClick={() => switchTo('projects')}
          label={t('sidebar.projects')}
        />
        <TabButton
          active={tab === 'collaborations'}
          onClick={() => switchTo('collaborations')}
          label={t('sidebar.collaborations')}
        />
      </div>
      {tab === 'chats' && <ChatsSection />}
      {tab === 'projects' && <ProjectsSection />}
      {tab === 'collaborations' && <CollaborationsSection />}
    </>
  )
}

/** 「對話」tab — 顯示「個人對話模式」標題;真正的 session list 在下方 list 區
 *  自動 filter 出 project_id=null 的(activeProjectId=null 由 switchTo 設定)。 */
function ChatsSection() {
  const { t } = useTranslation()
  return (
    <div className="mt-2 px-2">
      <div className="flex items-center gap-2 px-2 py-1.5 text-sm text-fg-base">
        <Inbox size={13} className="shrink-0" />
        <span className="flex-1 truncate text-left font-medium">
          {t('sidebar.personalConversations')}
        </span>
      </div>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean
  onClick: () => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`-mb-px flex-1 border-b-2 px-2 py-1.5 text-xs font-medium transition-colors ${
        active
          ? 'border-accent text-fg-base'
          : 'border-transparent text-fg-muted hover:text-fg-base'
      }`}
    >
      {label}
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
  // 互斥:collab 開著時,project 那邊 row 不該顯 active(視覺上 user 才看得出當前焦點在哪)
  const inCollab = useAgentStore((s) => s.currentCollaborationId !== null)
  const openCollaboration = useAgentStore((s) => s.openCollaboration)

  function selectProject(id: string | null) {
    setActiveProjectId(id)
    // 切到 project / 個人對話 = 退出任何開著的 collab view
    if (inCollab) openCollaboration(null)
  }

  return (
    <div className="mt-2 px-2">
      <div className="mb-1 flex justify-end px-1">
        <button
          type="button"
          onClick={openNewProject}
          title={t('sidebar.newProject')}
          className="rounded p-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <Plus size={12} />
        </button>
      </div>
      {projects.length === 0 && (
        <p className="px-2 text-xs text-fg-subtle">
          {t('sidebar.projectsEmpty')}
        </p>
      )}
      <ul className="flex flex-col gap-0.5">
        {projects.map((p) => (
          <li key={p.id}>
            <div
              className={`group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm ${
                activeProjectId === p.id && !inCollab
                  ? 'bg-bg-hover text-fg-base'
                  : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
              }`}
              title={p.workspace_dir ?? undefined}
            >
              <button
                type="button"
                onClick={() => selectProject(p.id)}
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

function CollaborationsSection() {
  const { t } = useTranslation()
  const collaborations = useAgentStore((s) => s.collaborations)
  const currentCollabId = useAgentStore((s) => s.currentCollaborationId)
  const openCollaboration = useAgentStore((s) => s.openCollaboration)
  const setCollaborations = useAgentStore((s) => s.setCollaborations)
  const openNewCollab = useSettingsStore((s) => s.openNewCollab)

  async function handleDelete(c: { id: string; name: string }, e: React.MouseEvent) {
    e.stopPropagation()
    const { deleteCollaboration, listCollaborations } = await import('../api/agent')
    if (!confirm(t('collab.deleteConfirm', { name: c.name }))) return
    await deleteCollaboration(c.id)
    // 若刪的是當前開著的 → 關掉 collab view 回到單視圖
    if (currentCollabId === c.id) {
      openCollaboration(null)
    }
    // 重 load list 更新 sidebar
    const items = await listCollaborations()
    setCollaborations(items.map((v) => ({
      id: v.collaboration.id,
      name: v.collaboration.name,
      workspace_dir: v.collaboration.workspace_dir,
      project_id: v.collaboration.project_id,
      budget_usd_cap: v.collaboration.budget_usd_cap,
      panes: v.panes.map((p) => ({
        session_id: p.session_id,
        pane_name: p.pane_name,
        pane_role: p.pane_role,
        pane_position: p.pane_position,
      })),
    })))
  }

  if (collaborations.length === 0) {
    // 沒任何 collab — 只放「+」按鈕讓使用者建立第一個 + 空狀態提示
    return (
      <div className="mt-2 px-2">
        <div className="mb-1 flex justify-end px-1">
          <button
            type="button"
            onClick={openNewCollab}
            title={t('sidebar.newCollaboration')}
            className="rounded p-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          >
            <Plus size={12} />
          </button>
        </div>
        <p className="px-2 text-xs text-fg-subtle">
          {t('collab.empty.sidebarHint')}
        </p>
      </div>
    )
  }

  return (
    <div className="mt-2 px-2">
      <div className="mb-1 flex justify-end px-1">
        <button
          type="button"
          onClick={openNewCollab}
          title={t('sidebar.newCollaboration')}
          className="rounded p-0.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <Plus size={12} />
        </button>
      </div>
      <ul className="flex flex-col gap-0.5">
        {collaborations.map((c) => {
          const active = currentCollabId === c.id
          return (
            <li key={c.id}>
              <div
                className={`group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm ${
                  active
                    ? 'bg-bg-hover text-fg-base'
                    : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
                }`}
                title={c.workspace_dir ?? undefined}
              >
                <button
                  type="button"
                  onClick={() => openCollaboration(c.id)}
                  className="flex flex-1 items-center gap-2 text-left"
                >
                  <Users size={13} className="shrink-0" />
                  <span className="flex-1 truncate">{c.name}</span>
                  <span className="shrink-0 text-[10px] text-fg-subtle">
                    {c.panes.length}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={(e) => handleDelete(c, e)}
                  title={t('collab.delete')}
                  className="opacity-0 group-hover:opacity-100 rounded p-0.5 text-fg-subtle hover:bg-bg-hover hover:text-red-400"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            </li>
          )
        })}
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
