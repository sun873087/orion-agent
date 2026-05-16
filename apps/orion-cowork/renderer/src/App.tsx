import { Sparkles } from 'lucide-react'

import { InputBox } from './components/InputBox'
import { MessageList } from './components/MessageList'
import { useAbort, useInitConversation, useSendPrompt } from './hooks/useAgent'
import { useAgentStore } from './store/agent'

export function App() {
  useInitConversation()
  const sendPrompt = useSendPrompt()
  const abort = useAbort()

  return (
    <div className="flex h-full w-full flex-col">
      <Header />
      <MessageList />
      <InputBox onSend={sendPrompt} onAbort={abort} />
    </div>
  )
}

function Header() {
  const sessionId = useAgentStore((s) => s.sessionId)
  const initError = useAgentStore((s) => s.initError)

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-bg-hover bg-bg-panel px-6">
      <div className="flex items-center gap-2">
        <Sparkles size={16} className="text-accent" />
        <h1 className="text-sm font-semibold">Orion Cowork</h1>
      </div>
      <div className="font-mono text-xs text-fg-subtle">
        {initError ? (
          <span className="text-error">{initError}</span>
        ) : sessionId ? (
          <span title={sessionId}>session: {sessionId.slice(0, 8)}</span>
        ) : (
          <span>initializing…</span>
        )}
      </div>
    </header>
  )
}
