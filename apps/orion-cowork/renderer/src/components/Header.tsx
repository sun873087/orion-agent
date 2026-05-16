import { useEffect, useState } from 'react'
import { Folder, PanelLeft, PanelLeftClose, Search, Sparkles } from 'lucide-react'

import { getPrefs, getProject, getSessionWorkspace } from '../api/agent'
import { useTranslation } from '../i18n'
import { useAgentStore } from '../store/agent'
import { useSettingsStore } from '../store/settings'

type WorkspaceState = {
  dir: string
  source: 'session' | 'project' | 'default'
} | null

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
  const [workspace, setWorkspace] = useState<WorkspaceState>(null)

  // session 變動 → 解析來源:session-level > project > default
  useEffect(() => {
    let cancelled = false
    async function resolve() {
      if (!sessionId) {
        // 沒 session 也顯 default workspace(若有)
        const prefs = await getPrefs().catch(() => ({} as Record<string, string>))
        if (cancelled) return
        const d = prefs.default_workspace_dir
        setWorkspace(d ? { dir: d, source: 'default' } : null)
        return
      }
      const ext = await getSessionWorkspace(sessionId).catch(() => null)
      if (cancelled) return
      if (ext?.workspace_dir) {
        setWorkspace({ dir: ext.workspace_dir, source: 'session' })
        return
      }
      if (ext?.project_id) {
        const p = await getProject(ext.project_id).catch(() => null)
        if (cancelled) return
        if (p?.project.workspace_dir) {
          setWorkspace({ dir: p.project.workspace_dir, source: 'project' })
          return
        }
      }
      const prefs = await getPrefs().catch(() => ({} as Record<string, string>))
      if (cancelled) return
      const d = prefs.default_workspace_dir
      setWorkspace(d ? { dir: d, source: 'default' } : null)
    }
    resolve()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  function shortName(dir: string): string {
    return dir.split('/').filter(Boolean).pop() || dir
  }

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
        {/* Workspace badge — read-only,顯示來源;點跳 Settings → General */}
        <button
          type="button"
          onClick={() => openSettings('general')}
          title={
            workspace
              ? `${workspace.dir}\n${t(`header.workspace.from.${workspace.source}`)}`
              : t('header.workspace.setInSettings')
          }
          className="flex items-center gap-1 rounded-md border border-bg-hover bg-bg-input px-2 py-1 text-xs hover:bg-bg-hover"
        >
          <Folder size={12} className="text-fg-muted" />
          {workspace ? (
            <>
              <span className="max-w-[160px] truncate font-mono text-fg-muted">
                {shortName(workspace.dir)}
              </span>
              <span className="rounded bg-bg-hover px-1 text-[10px] text-fg-subtle">
                {t(`header.workspace.source.${workspace.source}`)}
              </span>
            </>
          ) : (
            <span className="text-fg-muted">{t('header.workspace.none')}</span>
          )}
        </button>
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
