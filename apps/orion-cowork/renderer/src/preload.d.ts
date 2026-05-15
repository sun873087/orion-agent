/**
 * Mirror of contextBridge surface in electron/preload.ts。
 * 手寫一份保持 renderer 跟 main 兩邊不互相 import,符合 Electron 隔離原則。
 */

type StreamFrame = Record<string, unknown> & {
  id?: string
  event?: string
  data?: unknown
  final?: boolean
  error?: unknown
}

interface OrionAgentApi {
  call: (
    method: string,
    params: Record<string, unknown>,
    onFrame: (frame: StreamFrame) => void,
  ) => Promise<void>
}

declare global {
  interface Window {
    agent: OrionAgentApi
  }
}

export {}
