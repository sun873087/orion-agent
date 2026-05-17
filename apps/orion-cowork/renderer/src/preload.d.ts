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

interface OrionDialogApi {
  selectFolder: () => Promise<string | null>
  /** 寫 N 個檔到 {targetDir ?? ~/Downloads}/{bundleName}/ 下,自動 mkdir。
   *  encoding='utf8' 寫文字、'base64' 寫二進位(decode 後)。
   *  同名 bundleName 自動加 -1/-2 後綴。回 bundle 完整路徑(失敗回 null)。 */
  saveBundle: (
    bundleName: string,
    files: Array<{ relPath: string; content: string; encoding: 'utf8' | 'base64' }>,
    targetDir?: string,
  ) => Promise<string | null>
  /** 單檔寫入到 {targetDir ?? ~/Downloads}/{filename}。同名加 -1/-2 後綴。
   *  encoding='utf8' 寫文字、'base64' 寫二進位。回實際寫入完整路徑。 */
  saveFile: (
    filename: string,
    content: string,
    encoding: 'utf8' | 'base64',
    targetDir?: string,
  ) => Promise<string | null>
}

interface OrionShellApi {
  openPath: (path: string) => Promise<string | null>
  revealInFinder: (path: string) => Promise<null>
  /** 檢查路徑(檔或資料夾)是否實際存在於檔案系統。 */
  pathExists: (path: string) => Promise<boolean>
}

declare global {
  interface Window {
    agent: OrionAgentApi
    dialog: OrionDialogApi
    shellApi: OrionShellApi
  }
}

export {}
