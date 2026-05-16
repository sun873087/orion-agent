import { Header } from './components/Header'
import { InputBox } from './components/InputBox'
import { MessageList } from './components/MessageList'
import { SettingsPage } from './components/SettingsPage'
import { Sidebar } from './components/Sidebar'
import { useAbort, useInitConversation, useSendPrompt } from './hooks/useAgent'
import { useSettingsStore } from './store/settings'

export function App() {
  useInitConversation()
  const sendPrompt = useSendPrompt()
  const abort = useAbort()
  const settingsOpen = useSettingsStore((s) => s.settingsOpen)
  const sidebarCollapsed = useSettingsStore((s) => s.sidebarCollapsed)

  // Settings 是全頁 view — 開時整個 chat layout 被取代,不疊 modal。
  if (settingsOpen) {
    return <SettingsPage />
  }

  return (
    <div className="flex h-full w-full">
      {!sidebarCollapsed && <Sidebar />}
      <div className="flex flex-1 flex-col">
        <Header />
        <MessageList />
        <InputBox onSend={sendPrompt} onAbort={abort} />
      </div>
    </div>
  )
}
