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

const SIDEBAR_COLLAPSED_KEY = 'orion.sidebarCollapsed'

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn())
  const [currentSid, setCurrentSid] = useState<string | null>(null)
  // Draft 模式:使用者按了 New chat,但還沒送出第一則訊息;此時不打 backend
  // create,只在前端記住挑選的 model。送出第一則訊息時才實際建立 session。
  const [draft, setDraft] = useState<ModelChoice | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(
    () => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1',
  )
  const { sessions, loading, error, create, remove, refresh } = useSessions()
  const { catalog } = useModelCatalog()

  function toggleSidebar() {
    setSidebarCollapsed((c) => {
      const next = !c
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? '1' : '0')
      return next
    })
  }

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
    // draft 模式時不要自動跳到第一個 session
    if (!currentSid && !draft && sessions.length > 0) {
      setCurrentSid(sessions[0]!.session_id)
    }
    if (currentSid && !sessions.find((s) => s.session_id === currentSid)) {
      setCurrentSid(sessions[0]?.session_id ?? null)
    }
  }, [sessions, currentSid, draft])

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

  function newSession() {
    // 不打 backend — 切到 draft 模式,只在前端顯示空白歡迎畫面
    setCurrentSid(null)
    setDraft(defaultChoice() ?? null)
  }

  function selectSession(sid: string) {
    setDraft(null)
    setCurrentSid(sid)
  }

  async function commitDraft(): Promise<string | null> {
    // ChatView 在 draft mode 送出第一則訊息時呼叫;這裡才實際建立 session
    const s = await create(draft ?? undefined)
    if (!s) return null
    setPreferredModel({ provider: s.provider, model: s.model })
    setDraft(null)
    setCurrentSid(s.session_id)
    return s.session_id
  }

  async function onModelChange(choice: ModelChoice) {
    if (draft !== null) {
      // draft 模式只更新前端狀態,不打 backend
      setDraft(choice)
      return
    }
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
    setDraft(null)
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
        collapsed={sidebarCollapsed}
        onToggleCollapsed={toggleSidebar}
        onSelect={selectSession}
        onNew={newSession}
        onDelete={(sid) => void remove(sid)}
        onLogout={logout}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <ChatView
        sessionId={currentSid}
        token={token}
        currentSession={currentSession}
        catalog={catalog}
        draft={draft}
        onCommitDraft={commitDraft}
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
