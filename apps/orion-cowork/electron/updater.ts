/**
 * electron-updater wiring。
 *
 * 啟動後延遲 5s autoCheck;有新版 → 自動 download → notify renderer →
 * user 按 Restart 才 quit+install。
 *
 * Dev mode(NODE_ENV=development)不 check — 沒簽章的本地 build 會炸。
 *
 * 用 dynamic `require` 避免 hard import — 若 production build 漏掉
 * electron-updater(packaging 還沒做)也不會 crash。
 */
import type { BrowserWindow } from 'electron'

// electron-updater 的 minimal type shape — 避免裝 @types 依賴
type UpdateInfo = { version: string; releaseDate?: string }
type AutoUpdater = {
  autoDownload: boolean
  on: (event: string, listener: (...args: unknown[]) => void) => void
  checkForUpdates: () => Promise<unknown>
  quitAndInstall: () => void
}

let _updater: AutoUpdater | null = null

function _load(): AutoUpdater | null {
  if (_updater) return _updater
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('electron-updater') as { autoUpdater: AutoUpdater }
    _updater = mod.autoUpdater
    return _updater
  } catch (e) {
    console.warn('[updater] electron-updater not installed — skip auto-update', e)
    return null
  }
}

/** Init auto-updater + 把事件 forward 給 renderer windows。
 * `getWindows`:用 closure 抓 BrowserWindow list,避免 import 循環。
 */
export function initAutoUpdater(getWindows: () => BrowserWindow[]): void {
  if (process.env.NODE_ENV === 'development') {
    console.log('[updater] dev mode — auto-update disabled')
    return
  }
  const u = _load()
  if (!u) return

  u.autoDownload = true

  const broadcast = (channel: string, data: unknown): void => {
    for (const w of getWindows()) {
      if (!w.isDestroyed()) w.webContents.send(channel, data)
    }
  }

  u.on('checking-for-update', () => broadcast('updater:checking', {}))
  u.on('update-available', (info: unknown) => {
    broadcast('updater:available', info as UpdateInfo)
  })
  u.on('update-not-available', () => broadcast('updater:none', {}))
  u.on('download-progress', (p: unknown) => broadcast('updater:progress', p))
  u.on('update-downloaded', (info: unknown) => {
    broadcast('updater:downloaded', info as UpdateInfo)
  })
  u.on('error', (err: unknown) => {
    broadcast('updater:error', { message: String((err as Error)?.message ?? err) })
  })

  // 啟動後 5s 再 check — 讓 renderer 先 ready
  setTimeout(() => {
    u.checkForUpdates().catch((e) => {
      console.warn('[updater] check failed:', e)
    })
  }, 5000)
}

/** User 按「重啟並安裝」— quit + install。 */
export function quitAndInstall(): void {
  const u = _load()
  if (u) u.quitAndInstall()
}
