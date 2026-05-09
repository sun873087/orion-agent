import { useEffect, useState } from 'react'
import { clearAuth, getToken, getUsername, isLoggedIn } from './api/auth'
import { ChatView } from './components/ChatView'
import { Login } from './components/Login'
import { RightSidebar } from './components/RightSidebar'
import { SessionsSidebar } from './components/SessionsSidebar'
import { useSessions } from './hooks/useSessions'

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn())
  const [currentSid, setCurrentSid] = useState<string | null>(null)
  const { sessions, loading, error, create, remove, refresh } = useSessions()

  // 401 偵測 — 簡化版用 storage 事件追蹤
  useEffect(() => {
    function onStorage() {
      setAuthed(isLoggedIn())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  // 換 user / 新 login 時 refresh sessions
  useEffect(() => {
    if (authed) void refresh()
  }, [authed, refresh])

  // 自動選最新 session
  useEffect(() => {
    if (!currentSid && sessions.length > 0) {
      setCurrentSid(sessions[0]!.session_id)
    }
    if (currentSid && !sessions.find((s) => s.session_id === currentSid)) {
      setCurrentSid(sessions[0]?.session_id ?? null)
    }
  }, [sessions, currentSid])

  if (!authed) {
    return <Login onLoggedIn={() => setAuthed(true)} />
  }

  async function newSession() {
    const s = await create()
    if (s) setCurrentSid(s.session_id)
  }

  function logout() {
    clearAuth()
    setAuthed(false)
    setCurrentSid(null)
  }

  const token = getToken()

  return (
    <div className="h-full flex">
      <SessionsSidebar
        sessions={sessions}
        currentSessionId={currentSid}
        username={getUsername()}
        loading={loading}
        error={error}
        onSelect={setCurrentSid}
        onNew={() => void newSession()}
        onDelete={(sid) => void remove(sid)}
        onLogout={logout}
      />

      <ChatView sessionId={currentSid} token={token} />

      <RightSidebar sessionId={currentSid} />
    </div>
  )
}
