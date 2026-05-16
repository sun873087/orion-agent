import { useState } from 'react'

import { Header } from './components/Header'
import { InputBox } from './components/InputBox'
import { MessageList } from './components/MessageList'
import { SettingsPanel } from './components/SettingsPanel'
import { Sidebar } from './components/Sidebar'
import { useAbort, useInitConversation, useSendPrompt } from './hooks/useAgent'

export function App() {
  useInitConversation()
  const sendPrompt = useSendPrompt()
  const abort = useAbort()
  const [settingsOpen, setSettingsOpen] = useState(false)

  return (
    <div className="flex h-full w-full">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <Header onOpenSettings={() => setSettingsOpen(true)} />
        <MessageList />
        <InputBox onSend={sendPrompt} onAbort={abort} />
      </div>
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}
