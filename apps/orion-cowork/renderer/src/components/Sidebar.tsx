import { useEffect, useRef, useState } from 'react'
import {
  ChevronRight,
  Globe,
  MessageSquare,
  Plus,
  Settings as SettingsIcon,
  Trash2,
  User,
} from 'lucide-react'

import { useTranslation } from '../i18n'
import { useDeleteConversation, useNewConversation, useSwitchConversation } from '../hooks/useAgent'
import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

/** 左側對話列表 + 底部 user popup menu。menu 入口未來易擴(Profile / Shortcuts / Help…)。 */
export function Sidebar() {
  const { t } = useTranslation()
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
          <span>{t('sidebar.newChat')}</span>
        </button>
      </div>
      <div className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-3">
        {sessions.length === 0 ? (
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

/** Sidebar 左下 user 區塊 + popup menu。menu items 用 array,加項目只改 array。 */
function UserMenu() {
  const { t } = useTranslation()
  const openSettings = useSettingsStore((s) => s.openSettings)
  const openLanguagePanel = useSettingsStore((s) => s.openLanguagePanel)
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  // click outside / Escape 關 menu
  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onMouseDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const items: Array<{ key: string; label: string; icon: JSX.Element; onClick: () => void }> = [
    {
      key: 'settings',
      label: t('menu.settings'),
      icon: <SettingsIcon size={14} />,
      onClick: () => {
        setOpen(false)
        openSettings()
      },
    },
    {
      key: 'language',
      label: t('menu.language'),
      icon: <Globe size={14} />,
      onClick: () => {
        setOpen(false)
        openLanguagePanel()
      },
    },
  ]

  return (
    <div ref={rootRef} className="relative border-t border-bg-hover p-2">
      {open && (
        <div className="absolute bottom-full left-2 right-2 mb-1 rounded-lg border border-bg-hover bg-bg-base p-1 shadow-2xl">
          {items.map((it) => (
            <button
              key={it.key}
              type="button"
              onClick={it.onClick}
              className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-fg-base hover:bg-bg-hover"
            >
              <span className="flex items-center gap-2">
                {it.icon}
                <span>{it.label}</span>
              </span>
              <ChevronRight size={12} className="text-fg-subtle" />
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
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
