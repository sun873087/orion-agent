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
  /** 拿 drag-drop File 的絕對路徑(Electron 32+ webUtils 替代 file.path)。
   *  失敗或拿不到回空字串。 */
  getPathForFile: (file: File) => string
}

interface OrionSchedulerFiredPayload {
  schedule_id: string
  schedule_name: string
  session_id: string | null
  status: 'ok' | 'error' | 'skipped' | string
  error: string | null
  next_run_at: number | null
}

interface OrionSchedulerApi {
  /** 訂閱 sidecar 推的 scheduler.fired 事件。回傳 unsubscribe fn。 */
  onFired: (cb: (data: OrionSchedulerFiredPayload) => void) => () => void
}

interface OrionPlanModeAwaitingPayload {
  session_id: string
  plan_id: string | null
  plan_markdown: string
  plan_file_path: string | null
}

interface OrionPlanModeSessionEvent {
  session_id: string
  feedback?: string
}

interface OrionPlanApi {
  /** Plan submitted → 跳 approval modal。 */
  onAwaitingApproval: (cb: (data: OrionPlanModeAwaitingPayload) => void) => () => void
  /** Plan Mode 啟動(pending,下次 send 才 ACTIVE)。 */
  onEntered: (cb: (data: OrionPlanModeSessionEvent) => void) => () => void
  /** Plan Mode 關閉(從 active/awaiting 退出)。 */
  onExited: (cb: (data: OrionPlanModeSessionEvent) => void) => () => void
  onApproved: (cb: (data: OrionPlanModeSessionEvent) => void) => () => void
  onRejected: (cb: (data: OrionPlanModeSessionEvent) => void) => () => void
}

interface OrionBudgetExceededPayload {
  session_id: string
  current_usd: number
  budget_usd_cap: number
}

interface OrionBudgetApi {
  /** Session 累積成本超過 cap — Phase 31-Q。 */
  onExceeded: (cb: (data: OrionBudgetExceededPayload) => void) => () => void
}

declare global {
  interface Window {
    agent: OrionAgentApi
    dialog: OrionDialogApi
    shellApi: OrionShellApi
    /** 排程通知通道 — 不用 `scheduler` 因為跟 Chrome 91+ 內建
     *  `window.scheduler` (Scheduler API) 衝突,contextBridge 會擋。 */
    schedulerApi: OrionSchedulerApi
    /** Plan Mode 通知通道(Phase 31-J)。 */
    planApi: OrionPlanApi
    /** Budget 通知通道(Phase 31-Q)。 */
    budgetApi: OrionBudgetApi
  }
}

export {}
