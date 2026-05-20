/**
 * Preload script:在 isolated world 暴露 typed API 給 renderer。
 * Renderer 透過 window.agent.* 跟 main process 講話,main 再轉發給 sidecar。
 */

import { contextBridge, ipcRenderer, webUtils } from 'electron'

type StreamFrame = Record<string, unknown> & { id?: string; event?: string; final?: boolean }

let nextCallId = 0

const dialogApi = {
  selectFolder: async (): Promise<string | null> => {
    return ipcRenderer.invoke('dialog:selectFolder')
  },
  saveBundle: async (
    bundleName: string,
    files: Array<{ relPath: string; content: string; encoding: 'utf8' | 'base64' }>,
    targetDir?: string,
  ): Promise<string | null> => {
    return ipcRenderer.invoke('dialog:saveBundle', bundleName, files, targetDir)
  },
  saveFile: async (
    filename: string,
    content: string,
    encoding: 'utf8' | 'base64',
    targetDir?: string,
  ): Promise<string | null> => {
    return ipcRenderer.invoke('dialog:saveFile', filename, content, encoding, targetDir)
  },
}

const shellApi = {
  openPath: async (path: string): Promise<string | null> => {
    return ipcRenderer.invoke('shell:openPath', path)
  },
  revealInFinder: async (path: string): Promise<null> => {
    return ipcRenderer.invoke('shell:revealInFinder', path)
  },
  pathExists: async (path: string): Promise<boolean> => {
    return ipcRenderer.invoke('fs:pathExists', path)
  },
  /** 拿 drag-drop File 的絕對路徑(Electron 32+ 必須走 webUtils,
   *  舊 file.path API 已 deprecated)。 */
  getPathForFile: (file: File): string => {
    try {
      return webUtils.getPathForFile(file)
    } catch {
      return ''
    }
  },
}

type SchedulerFiredPayload = {
  schedule_id: string
  schedule_name: string
  session_id: string | null
  status: 'ok' | 'error' | 'skipped' | string
  error: string | null
  next_run_at: number | null
}

const schedulerApi = {
  /** 訂閱 sidecar 推的 scheduler.fired 事件。回傳一個 unsubscribe fn。 */
  onFired: (cb: (data: SchedulerFiredPayload) => void): (() => void) => {
    const listener = (_: unknown, data: SchedulerFiredPayload) => cb(data)
    ipcRenderer.on('scheduler:fired', listener)
    return () => ipcRenderer.removeListener('scheduler:fired', listener)
  },
}

type PlanModeAwaitingPayload = {
  session_id: string
  plan_id: string | null
  plan_markdown: string
  plan_file_path: string | null
}
type PlanModeSessionEvent = { session_id: string; feedback?: string }

const planApi = {
  /** Plan submitted, awaiting user approval — renderer 跳 modal。 */
  onAwaitingApproval: (cb: (data: PlanModeAwaitingPayload) => void): (() => void) => {
    const listener = (_: unknown, data: PlanModeAwaitingPayload) => cb(data)
    ipcRenderer.on('plan_mode:awaiting_approval', listener)
    return () => ipcRenderer.removeListener('plan_mode:awaiting_approval', listener)
  },
  /** User /plan 開啟 / Pill 切 Plan → sidecar 確認 pending。 */
  onEntered: (cb: (data: PlanModeSessionEvent) => void): (() => void) => {
    const listener = (_: unknown, data: PlanModeSessionEvent) => cb(data)
    ipcRenderer.on('plan_mode:entered', listener)
    return () => ipcRenderer.removeListener('plan_mode:entered', listener)
  },
  onExited: (cb: (data: PlanModeSessionEvent) => void): (() => void) => {
    const listener = (_: unknown, data: PlanModeSessionEvent) => cb(data)
    ipcRenderer.on('plan_mode:exited', listener)
    return () => ipcRenderer.removeListener('plan_mode:exited', listener)
  },
  onApproved: (cb: (data: PlanModeSessionEvent) => void): (() => void) => {
    const listener = (_: unknown, data: PlanModeSessionEvent) => cb(data)
    ipcRenderer.on('plan_mode:approved', listener)
    return () => ipcRenderer.removeListener('plan_mode:approved', listener)
  },
  onRejected: (cb: (data: PlanModeSessionEvent) => void): (() => void) => {
    const listener = (_: unknown, data: PlanModeSessionEvent) => cb(data)
    ipcRenderer.on('plan_mode:rejected', listener)
    return () => ipcRenderer.removeListener('plan_mode:rejected', listener)
  },
}

type BackupRestartPayload = {
  reason: string
  moved_to: string
}

const backupApi = {
  /** Save dialog 拿 .zip 路徑;canceled → null。 */
  pickSavePath: async (defaultName: string): Promise<string | null> => {
    return ipcRenderer.invoke('dialog:pickBackupSavePath', defaultName)
  },
  /** Open dialog 拿 .zip 路徑;canceled → null。 */
  pickOpenPath: async (): Promise<string | null> => {
    return ipcRenderer.invoke('dialog:pickBackupOpenPath')
  },
  /** Restore 完成 — sidecar 推 backup.restart_required。renderer 訂閱顯重啟 UI。 */
  onRestartRequired: (cb: (data: BackupRestartPayload) => void): (() => void) => {
    const listener = (_: unknown, data: BackupRestartPayload) => cb(data)
    ipcRenderer.on('backup:restart_required', listener)
    return () => ipcRenderer.removeListener('backup:restart_required', listener)
  },
  /** 重啟整個 app(app.relaunch + quit)。 */
  relaunch: async (): Promise<void> => {
    return ipcRenderer.invoke('app:relaunch')
  },
}

type BudgetExceededPayload = {
  session_id: string
  current_usd: number
  budget_usd_cap: number
}

const budgetApi = {
  /** Session 累積成本超過 cap — renderer 顯 banner + toast(Phase 31-Q)。 */
  onExceeded: (cb: (data: BudgetExceededPayload) => void): (() => void) => {
    const listener = (_: unknown, data: BudgetExceededPayload) => cb(data)
    ipcRenderer.on('budget:exceeded', listener)
    return () => ipcRenderer.removeListener('budget:exceeded', listener)
  },
}

const agentApi = {
  /**
   * 呼叫 sidecar RPC。`onFrame` 每個 streaming frame 觸發一次。
   * 回傳 Promise 在 final frame 收到時 resolve。
   */
  call: (
    method: string,
    params: Record<string, unknown>,
    onFrame: (frame: StreamFrame) => void,
  ): Promise<void> => {
    const callId = `c-${nextCallId++}`
    const channel = `agent-frame:${callId}`
    return new Promise((resolveCall, rejectCall) => {
      const listener = (_: unknown, frame: StreamFrame) => {
        onFrame(frame)
        if (frame.final) {
          ipcRenderer.removeListener(channel, listener)
          if (frame.error) {
            // 抽 user-friendly message 出來,不要 dump 整個 JSON 給 UI
            // (sidecar 已用 `_format_send_error` map 成可讀文字)
            const err = frame.error as { code?: string; message?: string } | string
            let msg = ''
            let code: string | undefined
            if (typeof err === 'string') {
              msg = err
            } else if (err && typeof err === 'object') {
              msg = String(err.message ?? '')
              code = err.code ? String(err.code) : undefined
            }
            const e = new Error(msg || 'unknown error')
            ;(e as Error & { code?: string }).code = code
            rejectCall(e)
          } else {
            resolveCall()
          }
        }
      }
      ipcRenderer.on(channel, listener)
      ipcRenderer.send('agent:call', { callId, method, params })
    })
  },
}

contextBridge.exposeInMainWorld('agent', agentApi)
contextBridge.exposeInMainWorld('dialog', dialogApi)
contextBridge.exposeInMainWorld('shellApi', shellApi)
// 注意:不能用 'scheduler' — Chrome 91+ window.scheduler 是內建 Scheduler API
// (postTask 那組),contextBridge 不能覆寫,會丟「Cannot bind an API on top of
// an existing property」。改用 'schedulerApi' 跟 'shellApi' 對齊。
contextBridge.exposeInMainWorld('schedulerApi', schedulerApi)
contextBridge.exposeInMainWorld('planApi', planApi)
contextBridge.exposeInMainWorld('budgetApi', budgetApi)
contextBridge.exposeInMainWorld('backupApi', backupApi)

declare global {
  interface Window {
    agent: typeof agentApi
    dialog: typeof dialogApi
    shellApi: typeof shellApi
    schedulerApi: typeof schedulerApi
    planApi: typeof planApi
    budgetApi: typeof budgetApi
    backupApi: typeof backupApi
  }
}
