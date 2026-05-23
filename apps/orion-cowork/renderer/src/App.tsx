import { useEffect } from 'react'

import { listCollaborations } from './api/agent'
import { AddPaneModal } from './components/AddPaneModal'
import { ForkPromptModal } from './components/ForkPromptModal'
import { Header } from './components/Header'
import { InputBox } from './components/InputBox'
import { MessageList } from './components/MessageList'
import { MultiPaneView } from './components/MultiPaneView'
import { NewCollaborationModal } from './components/NewCollaborationModal'
import { NewProjectModal } from './components/NewProjectModal'
import { PlanApprovalModal } from './components/PlanApprovalModal'
import { ProjectSettingsPage } from './components/ProjectSettingsPage'
import { RightSidebar } from './components/RightSidebar'
import { SettingsPage } from './components/SettingsPage'
import { Sidebar } from './components/Sidebar'
import {
  useAbort,
  useBudgetNotifications,
  useInitConversation,
  usePlanModeNotifications,
  useFollowUpsUpdates,
  usePlanStatusRehydrate,
  useScheduleNotifications,
  useSendPrompt,
  useSessionTitleUpdates,
} from './hooks/useAgent'
import { useAgentStore } from './store/agent'
import { useSettingsStore } from './store/settings'

export function App() {
  useInitConversation()
  useScheduleNotifications()
  usePlanModeNotifications()
  usePlanStatusRehydrate()
  useBudgetNotifications()
  useSessionTitleUpdates()
  useFollowUpsUpdates()
  useLoadCollaborations()
  const sendPrompt = useSendPrompt()
  const abort = useAbort()
  const settingsOpen = useSettingsStore((s) => s.settingsOpen)
  const editingProjectId = useSettingsStore((s) => s.editingProjectId)
  const sidebarCollapsed = useSettingsStore((s) => s.sidebarCollapsed)
  const rightSidebarOpen = useSettingsStore((s) => s.rightSidebarOpen)
  const isEmpty = useAgentStore((s) => {
    const sid = s.sessionId
    if (!sid) return true
    return (s.messagesBySession[sid] ?? []).length === 0
  })
  const collaborationId = useAgentStore((s) => s.currentCollaborationId)

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
          {collaborationId ? (
            // Multi-pane collaboration view —上面 N pane,下面 InputBox 送到 active pane
            <>
              <div className="flex-1 overflow-hidden">
                <MultiPaneView />
              </div>
              <InputBox onSend={sendPrompt} onAbort={abort} />
            </>
          ) : isEmpty ? (
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
      <NewCollaborationModal />
      <AddPaneModal />
      <PlanApprovalModal />
      <ForkPromptModal />
    </div>
  )
}

/** 啟動時載入所有 collaborations 進 store。新增 / 加 pane 完成的 mutator
 *  自己會 set,這 hook 只負責「first-load 從空 → DB 的 state 同步」。 */
function useLoadCollaborations() {
  const setCollaborations = useAgentStore((s) => s.setCollaborations)
  useEffect(() => {
    void (async () => {
      try {
        const items = await listCollaborations()
        setCollaborations(items.map((v) => ({
          id: v.collaboration.id,
          name: v.collaboration.name,
          workspace_dir: v.collaboration.workspace_dir,
          project_id: v.collaboration.project_id,
          budget_usd_cap: v.collaboration.budget_usd_cap,
          panes: v.panes.map((p) => ({
            session_id: p.session_id,
            pane_name: p.pane_name,
            pane_role: p.pane_role,
            pane_position: p.pane_position,
          })),
        })))
      } catch {
        // 啟動時 sidecar 還沒 ready 也可能失敗 — 沒 collab 不要擋啟動,
        // 後續用者建立第一個 collab 時 modal submit 端會重 load。
      }
    })()
  }, [setCollaborations])
}
