import { PanelLeft, PanelLeftClose, Search, Sparkles } from 'lucide-react'

import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

export function Header() {
  const { t } = useTranslation()
  const sessionId = useAgentStore((s) => s.sessionId)
  const initError = useAgentStore((s) => s.initError)
  const provider = useSettingsStore((s) => s.selectedProvider)
  const model = useSettingsStore((s) => s.selectedModel)
  const openSettings = useSettingsStore((s) => s.openSettings)
  const sidebarCollapsed = useSettingsStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useSettingsStore((s) => s.toggleSidebar)
  const toggleSidebarSearch = useSettingsStore((s) => s.toggleSidebarSearch)

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-bg-hover bg-bg-panel px-3">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={toggleSidebar}
          title={t(sidebarCollapsed ? 'sidebar.expand' : 'sidebar.collapse')}
          className="flex h-8 w-8 items-center justify-center rounded-md text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          {sidebarCollapsed ? <PanelLeft size={16} /> : <PanelLeftClose size={16} />}
        </button>
        <button
          type="button"
          onClick={toggleSidebarSearch}
          title={t('sidebar.search')}
          className="flex h-8 w-8 items-center justify-center rounded-md text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <Search size={16} />
        </button>
        <div className="ml-2 flex items-center gap-2">
          <Sparkles size={16} className="text-accent" />
          <h1 className="text-sm font-semibold">{t('app.title')}</h1>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => openSettings('models')}
          className="flex items-center gap-2 rounded-md border border-bg-hover bg-bg-input px-2 py-1 font-mono text-xs text-fg-muted hover:bg-bg-hover hover:text-fg-base"
          title={t('settings.title')}
        >
          <span>{provider}</span>
          <span className="text-fg-subtle">/</span>
          <span>{model}</span>
        </button>

        <span className="font-mono text-xs text-fg-subtle">
          {initError ? (
            <span className="text-error">{initError}</span>
          ) : sessionId ? (
            <span title={sessionId}>{t('session.label', { id: sessionId.slice(0, 8) })}</span>
          ) : (
            <span>{t('app.initializing')}</span>
          )}
        </span>
      </div>
    </header>
  )
}
