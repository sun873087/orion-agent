/**
 * Electron main process — Phase E PoC。
 *
 * - 開一個 BrowserWindow,dev 載 vite (:5174),prod 載 dist/renderer/index.html
 * - 啟動 Python sidecar,等 ready
 * - 註冊 IPC handler 把 renderer 的 call 路由到 sidecar
 */

import { BrowserWindow, app, ipcMain } from 'electron'
import { resolve } from 'node:path'

import { SidecarClient, findRepoRoot } from './sidecar'

const isDev = process.env.NODE_ENV === 'development'
const sidecar = new SidecarClient()

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
  if (isDev) {
    await win.loadURL('http://127.0.0.1:5174')
    win.webContents.openDevTools({ mode: 'detach' })
  } else {
    await win.loadFile(resolve(__dirname, '..', 'renderer', 'index.html'))
  }
}

app.whenReady().then(async () => {
  // 1. 啟 sidecar
  sidecar.start(findRepoRoot())
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

app.on('window-all-closed', async () => {
  await sidecar.dispose()
  if (process.platform !== 'darwin') app.quit()
})

app.on('will-quit', async (e) => {
  e.preventDefault()
  await sidecar.dispose()
  app.exit(0)
})
