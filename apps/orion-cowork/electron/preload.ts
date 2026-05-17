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

declare global {
  interface Window {
    agent: typeof agentApi
    dialog: typeof dialogApi
    shellApi: typeof shellApi
  }
}
