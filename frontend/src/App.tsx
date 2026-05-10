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
import { useSessions } from './hooks/useSessions'
import {
  getPreferredModel,
  setPreferredModel,
  type ModelChoice,
} from './lib/preferredModel'

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn())
  const [currentSid, setCurrentSid] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { sessions, loading, error, create, remove, refresh } = useSessions()
  const { catalog } = useModelCatalog()

  useEffect(() => {
    function onStorage() {
      setAuthed(isLoggedIn())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  useEffect(() => {
    if (authed) void refresh()
  }, [authed, refresh])

  useEffect(() => {
    if (!currentSid && sessions.length > 0) {
      setCurrentSid(sessions[0]!.session_id)
    }
    if (currentSid && !sessions.find((s) => s.session_id === currentSid)) {
      setCurrentSid(sessions[0]?.session_id ?? null)
    }
  }, [sessions, currentSid])

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

  async function newSession() {
    const s = await create(defaultChoice())
    if (s) {
      setCurrentSid(s.session_id)
      setPreferredModel({ provider: s.provider, model: s.model })
    }
  }

  async function onModelChange(choice: ModelChoice) {
    // 把上一個 empty session 刪掉(picker 只在 empty state 出現,這必為空)
    if (currentSid && currentSession && currentSession.n_messages === 0) {
      await remove(currentSid)
    }
    const s = await create(choice)
    if (s) {
      setCurrentSid(s.session_id)
      setPreferredModel({ provider: s.provider, model: s.model })
    }
  }

  function logout() {
    clearAuth()
    resetModelCatalogCache()
    setAuthed(false)
    setCurrentSid(null)
    setSettingsOpen(false)
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
        onSelect={setCurrentSid}
        onNew={() => void newSession()}
        onDelete={(sid) => void remove(sid)}
        onLogout={logout}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <ChatView
        sessionId={currentSid}
        token={token}
        currentSession={currentSession}
        catalog={catalog}
        onOpenSettings={() => setSettingsOpen(true)}
        onModelChange={(c) => void onModelChange(c)}
      />

      {settingsOpen && (
        <SettingsModal
          sessionId={currentSid}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  )
}
