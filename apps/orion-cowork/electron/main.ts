/**
 * Electron main process — Phase E PoC。
 *
 * - 開一個 BrowserWindow,dev 載 vite (:5174),prod 載 dist/renderer/index.html
 * - 啟動 Python sidecar,等 ready
 * - 註冊 IPC handler 把 renderer 的 call 路由到 sidecar
 */

import { BrowserWindow, app, ipcMain } from 'electron'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { SidecarClient, findRepoRoot } from './sidecar'

const isDev = process.env.NODE_ENV === 'development'
const sidecar = new SidecarClient()

/**
 * Production:Contents/Resources/sidecar/orion-cowork-sidecar(macOS / Linux)
 * 或 resources\sidecar\orion-cowork-sidecar.exe(Windows)
 * Dev:回 null,SidecarClient 走 uv run fallback
 */
function packagedSidecarPath(): string | null {
  if (!app.isPackaged) return null
  const ext = process.platform === 'win32' ? '.exe' : ''
  const p = resolve(process.resourcesPath, 'sidecar', `orion-cowork-sidecar${ext}`)
  return existsSync(p) ? p : null
}

async function createWindow(): Promise<void> {
  const win = new BrowserWindow({
    width: 1100,
    height: 800,
    webPreferences: {
      preload: resolve(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  // Drop 檔案到非 InputBox 區域時,Electron 預設行為是 navigate 到該檔(取代整個
  // renderer)。我們不要那個 — file:// navigation 一律擋掉,讓 renderer 自己的
  // onDrop handler 處理。
  win.webContents.on('will-navigate', (e, url) => {
    if (url.startsWith('file://')) e.preventDefault()
  })

  if (isDev) {
    await win.loadURL('http://127.0.0.1:5174')
    win.webContents.openDevTools({ mode: 'detach' })
  } else {
    await win.loadFile(resolve(__dirname, '..', 'renderer', 'index.html'))
  }
}

app.whenReady().then(async () => {
  // 1. 啟 sidecar(production 用打包 binary,dev 用 uv run)
  sidecar.start(findRepoRoot(), packagedSidecarPath())
  await sidecar.waitReady()
  console.log('[main] sidecar ready')

  // 2. 註冊 IPC
  ipcMain.on('agent:call', async (event, msg: { callId: string; method: string; params: Record<string, unknown> }) => {
    const channel = `agent-frame:${msg.callId}`
    try {
      await sidecar.call(msg.method, msg.params, (frame) => {
        event.sender.send(channel, frame)
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      event.sender.send(channel, { id: msg.callId, error: { code: 'IPC_ERROR', message }, final: true })
    }
  })

  // 3. 開窗
  await createWindow()
})

// 全平台統一:關閉視窗 = 結束 app(macOS 不再保留 dock,user 預期行為)。
app.on('window-all-closed', () => {
  app.quit()
})

// before-quit 階段先把 sidecar 收乾淨,避免 zombie 進程。
let quitting = false
app.on('before-quit', async (e) => {
  if (quitting) return
  e.preventDefault()
  quitting = true
  try {
    await sidecar.dispose()
  } catch (err) {
    console.error('[main] sidecar dispose error:', err)
  }
  app.exit(0)
})
