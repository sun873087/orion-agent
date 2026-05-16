import { Header } from './components/Header'
import { InputBox } from './components/InputBox'
import { MessageList } from './components/MessageList'
import { NewProjectModal } from './components/NewProjectModal'
import { ProjectSettingsPage } from './components/ProjectSettingsPage'
import { RightSidebar } from './components/RightSidebar'
import { SettingsPage } from './components/SettingsPage'
import { Sidebar } from './components/Sidebar'
import { useAbort, useInitConversation, useSendPrompt } from './hooks/useAgent'
import { useAgentStore } from './store/agent'
import { useSettingsStore } from './store/settings'

export function App() {
  useInitConversation()
  const sendPrompt = useSendPrompt()
  const abort = useAbort()
  const settingsOpen = useSettingsStore((s) => s.settingsOpen)
  const editingProjectId = useSettingsStore((s) => s.editingProjectId)
  const sidebarCollapsed = useSettingsStore((s) => s.sidebarCollapsed)
  const rightSidebarOpen = useSettingsStore((s) => s.rightSidebarOpen)
  const isEmpty = useAgentStore((s) => s.messages.length === 0)

  // 全頁 views 優先(取代 chat layout)
  if (settingsOpen) return <SettingsPage />
  if (editingProjectId) return <ProjectSettingsPage />

  // 頂端 toolbar 跨整個 window(macOS 嵌入紅綠燈),底下 content row
  return (
    <div className="flex h-full w-full flex-col">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        {!sidebarCollapsed && <Sidebar />}
        {/* min-w-0 讓 chat column 在 flex 內可縮,內容 wrap 而非 overflow */}
        <div className="flex min-w-0 flex-1 flex-col">
          {isEmpty ? (
            // Empty state:InputBox 垂直置中,hero 在 box 上方(Claude Cowork 風格)
            <div className="flex flex-1 items-center justify-center overflow-hidden">
              <div className="w-full">
                <InputBox onSend={sendPrompt} onAbort={abort} />
              </div>
            </div>
          ) : (
            <>
              <MessageList />
              <InputBox onSend={sendPrompt} onAbort={abort} />
            </>
          )}
        </div>
        {rightSidebarOpen && <RightSidebar />}
      </div>
      <NewProjectModal />
    </div>
  )
}
