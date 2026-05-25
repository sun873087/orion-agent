import { useEffect, useMemo, useState } from 'react'
import { clearAuth, getToken, getUsername, isLoggedIn } from './api/auth'
import { ChatView } from './components/ChatView'
import { Login } from './components/Login'
import { SessionsSidebar } from './components/SessionsSidebar'
import { SettingsModal } from './components/SettingsModal'
import {
  resetModelCatalogCache,
  useModelCatalog,
} from './hooks/useModelCatalog'
import { useSessionStore } from './store/sessionStore'
import { useUiStore } from './store/uiStore'
import { getPreferredModel, type ModelChoice } from './lib/preferredModel'

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn())
  const {
    sessions,
    loading,
    error,
    currentSid,
    draft,
    refresh,
    selectSession,
    startDraft,
    commitDraft,
    changeModel,
    remove,
    rename,
    toggleStar,
    forkSession,
    reset,
  } = useSessionStore()
  const settingsOpen = useUiStore((s) => s.settingsOpen)
  const openSettings = useUiStore((s) => s.openSettings)
  const closeSettings = useUiStore((s) => s.closeSettings)
  const sidebarCollapsed = useUiStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  const hydrateLocale = useUiStore((s) => s.hydrateLocaleFromBackend)
  const { catalog, refresh: refreshCatalog } = useModelCatalog()

  function newChat() {
    // 開新對話時重抓可用 model(provider key / Ollama 模型可能已變)
    refreshCatalog()
    startDraft(defaultChoice() ?? null)
  }

  useEffect(() => {
    function onStorage() {
      setAuthed(isLoggedIn())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  useEffect(() => {
    if (authed) {
      void refresh()
      void hydrateLocale()
    }
  }, [authed, refresh, hydrateLocale])

  const currentSession = useMemo(
    () => sessions.find((s) => s.session_id === currentSid) ?? null,
    [sessions, currentSid],
  )

  function defaultChoice(): ModelChoice | undefined {
    const stored = getPreferredModel()
    if (stored) return stored
    if (catalog) return catalog.default
    return undefined
  }

  if (!authed) {
    return <Login onLoggedIn={() => setAuthed(true)} />
  }

  function logout() {
    clearAuth()
    resetModelCatalogCache()
    reset()
    closeSettings()
    setAuthed(false)
  }

  const token = getToken()

  return (
    <div className="h-full flex bg-claude-cream text-claude-text">
      <SessionsSidebar
        sessions={sessions}
        currentSessionId={currentSid}
        username={getUsername()}
        loading={loading}
        error={error}
        catalog={catalog}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={toggleSidebar}
        onSelect={selectSession}
        onNew={newChat}
        onDelete={(sid) => void remove(sid)}
        onRename={(sid, title) => void rename(sid, title)}
        onToggleStar={(sid) => void toggleStar(sid)}
        onFork={(sid) => void forkSession(sid)}
        onLogout={logout}
        onOpenSettings={openSettings}
      />

      <ChatView
        sessionId={currentSid}
        token={token}
        currentSession={currentSession}
        catalog={catalog}
        draft={draft}
        onCommitDraft={commitDraft}
        onOpenSettings={openSettings}
        onModelChange={(c) => void changeModel(c)}
      />

      {settingsOpen && (
        <SettingsModal onClose={closeSettings} />
      )}
    </div>
  )
}
