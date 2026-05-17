/**
 * Preload script:在 isolated world 暴露 typed API 給 renderer。
 * Renderer 透過 window.agent.* 跟 main process 講話,main 再轉發給 sidecar。
 */

import { contextBridge, ipcRenderer } from 'electron'

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
          if (frame.error) rejectCall(new Error(JSON.stringify(frame.error)))
          else resolveCall()
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

declare global {
  interface Window {
    agent: typeof agentApi
    dialog: typeof dialogApi
    shellApi: typeof shellApi
    schedulerApi: typeof schedulerApi
  }
}
