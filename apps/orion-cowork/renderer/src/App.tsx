import { Header } from './components/Header'
import { InputBox } from './components/InputBox'
import { MessageList } from './components/MessageList'
import { NewProjectModal } from './components/NewProjectModal'
import { ProjectSettingsPage } from './components/ProjectSettingsPage'
import { RightSidebar } from './components/RightSidebar'
import { SettingsPage } from './components/SettingsPage'
import { Sidebar } from './components/Sidebar'
import { useAbort, useInitConversation, useSendPrompt } from './hooks/useAgent'
import { useSettingsStore } from './store/settings'

export function App() {
  useInitConversation()
  const sendPrompt = useSendPrompt()
  const abort = useAbort()
  const settingsOpen = useSettingsStore((s) => s.settingsOpen)
  const editingProjectId = useSettingsStore((s) => s.editingProjectId)
  const sidebarCollapsed = useSettingsStore((s) => s.sidebarCollapsed)
  const rightSidebarOpen = useSettingsStore((s) => s.rightSidebarOpen)

  // 全頁 views 優先(取代 chat layout)
  if (settingsOpen) return <SettingsPage />
  if (editingProjectId) return <ProjectSettingsPage />

  return (
    <div className="flex h-full w-full">
      {!sidebarCollapsed && <Sidebar />}
      <div className="flex flex-1 flex-col">
        <Header />
        <MessageList />
        <InputBox onSend={sendPrompt} onAbort={abort} />
      </div>
      {rightSidebarOpen && <RightSidebar />}
      <NewProjectModal />
    </div>
  )
}
