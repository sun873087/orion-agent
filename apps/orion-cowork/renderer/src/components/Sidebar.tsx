import { useEffect, useRef, useState } from 'react'
import {
  Check,
  ChevronRight,
  Globe,
  MessageSquare,
  Plus,
  Search,
  Settings as SettingsIcon,
  Trash2,
  User,
  X,
} from 'lucide-react'

import { searchConversations, type SearchHit } from '../api/agent'
import { LOCALES, useTranslation, type Locale } from '../i18n'
import { useDeleteConversation, useNewConversation, useSwitchConversation } from '../hooks/useAgent'
import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

/** 左側對話列表 + 底部 user popup menu(支援 nested submenu)。 */
export function Sidebar() {
  const { t } = useTranslation()
  const sessions = useAgentStore((s) => s.sessions)
  const currentId = useAgentStore((s) => s.sessionId)
  const newConv = useNewConversation()
  const switchTo = useSwitchConversation()
  const del = useDeleteConversation()
  const searchOpen = useSettingsStore((s) => s.sidebarSearchOpen)
  const searchQuery = useSettingsStore((s) => s.sidebarSearchQuery)
  const setSearchQuery = useSettingsStore((s) => s.setSidebarSearchQuery)
  const toggleSearch = useSettingsStore((s) => s.toggleSidebarSearch)

  // Backend full-text search:有 query 時 debounce 300ms call sidecar;空就清空
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
      <div className="p-3">
        <button
          type="button"
          onClick={newConv}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          <Plus size={14} />
          <span>{t('sidebar.newChat')}</span>
        </button>
      </div>
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
        ) : sessions.length === 0 ? (
          <div className="px-3 py-2 text-xs text-fg-subtle">{t('sidebar.empty')}</div>
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
                        <span className="text-fg-subtle italic">{t('sidebar.newConversation')}</span>
                      )}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (window.confirm(t('sidebar.deleteConfirm'))) {
                          del(s.session_id)
                        }
                      }}
                      title={t('sidebar.deleteTooltip')}
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

      <UserMenu />
    </aside>
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
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/20 text-accent">
          <User size={14} />
        </div>
        <span className="flex-1 truncate text-left">{t('sidebar.localUser')}</span>
      </button>
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
