/**
 * Electron main process — Phase E PoC。
 *
 * - 開一個 BrowserWindow,dev 載 vite (:5174),prod 載 dist/renderer/index.html
 * - 啟動 Python sidecar,等 ready
 * - 註冊 IPC handler 把 renderer 的 call 路由到 sidecar
 */

import { BrowserWindow, app, dialog, ipcMain, nativeImage, session, shell } from 'electron'
import { existsSync, promises as fsPromises } from 'node:fs'
import { join, parse, resolve } from 'node:path'

/**
 * Dev mode 載 build/icon.png — 讓 Dock(macOS)/ taskbar(Win/Linux)顯
 * 自訂 icon。 production 由 electron-builder 自動讀 build/icon.{icns,ico,png}
 * 打進 .app/.exe。 user 把 1024x1024 PNG 放 build/icon.png 就生效。
 */
function customIconPath(): string | null {
  // dev 跑 electron . 時 __dirname = apps/orion-cowork/dist/electron/
  // production .app 內路徑不同,但已由 builder 處理 — 此 fn 只 dev 用。
  const candidates = [
    resolve(__dirname, '..', '..', 'build', 'icon.png'),
    resolve(__dirname, '..', '..', 'build', 'icon.icns'),
  ]
  for (const p of candidates) {
    if (existsSync(p)) return p
  }
  return null
}

import { SidecarClient, findRepoRoot } from './sidecar'

const isDev = process.env.NODE_ENV === 'development'

// Dev mode 跑 `electron .` 預設 name 是 "Electron"(dock hover / menu bar 都
// 顯這個)。 production 由 electron-builder productName 處理,dev 也補上。
app.setName('Orion Cowork')

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
  const isMac = process.platform === 'darwin'
  const iconPath = customIconPath()
  // macOS:dock.setIcon 在 app.whenReady 後(see 下方);Win/Linux BrowserWindow.icon
  const win = new BrowserWindow({
    width: 1100,
    height: 800,
    icon: iconPath && !isMac ? iconPath : undefined,
    // macOS:嵌入式紅綠燈,React 自畫整個頂端 toolbar,跟 Claude.ai 風格一致
    titleBarStyle: isMac ? 'hiddenInset' : 'default',
    trafficLightPosition: isMac ? { x: 14, y: 14 } : undefined,
    webPreferences: {
      preload: resolve(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })
  if (isMac && iconPath && app.dock) {
    try {
      app.dock.setIcon(nativeImage.createFromPath(iconPath))
    } catch (err) {
      console.warn('[main] dock.setIcon failed:', err)
    }
  }

  // Web Speech API / getUserMedia 需要 media 權限 — local app 一律放行,
  // 否則 mic 按鈕按下後 webkitSpeechRecognition 直接 onerror。
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    if (permission === 'media' || permission === 'mediaKeySystem') {
      callback(true)
      return
    }
    callback(false)
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

  // Forward sidecar background notifications (排程觸發等) 給所有 renderer windows。
  // 用法:renderer 透過 preload `window.scheduler.onFired(cb)` 訂閱。
  sidecar.onNotification((frame) => {
    const evt = frame.event as string | undefined
    if (!evt) return
    const data = frame.data as Record<string, unknown> | undefined
    const broadcast = (channel: string): void => {
      for (const w of BrowserWindow.getAllWindows()) {
        if (!w.isDestroyed()) w.webContents.send(channel, data ?? {})
      }
    }
    if (evt === 'scheduler.fired') broadcast('scheduler:fired')
    else if (evt === 'plan_mode.awaiting_approval') broadcast('plan_mode:awaiting_approval')
    else if (evt === 'plan_mode.entered') broadcast('plan_mode:entered')
    else if (evt === 'plan_mode.exited') broadcast('plan_mode:exited')
    else if (evt === 'plan_mode.approved') broadcast('plan_mode:approved')
    else if (evt === 'plan_mode.rejected') broadcast('plan_mode:rejected')
    else if (evt === 'budget.exceeded') broadcast('budget:exceeded')
  })

  // 2. 註冊 IPC
  ipcMain.on('agent:call', async (event, msg: { callId: string; method: string; params: Record<string, unknown> }) => {
    const channel = `agent-frame:${msg.callId}`
    // sidecar 還在 in-flight 時若 window 被關掉 / 銷毀(e.g. user 關 app
    // 視窗的瞬間 sidecar.exit 還在處理 pending RPC),event.sender 變
    // destroyed,send() 就丟 "Object has been destroyed"。包一層 safe send。
    const safeSend = (payload: unknown): void => {
      const sender = event.sender
      if (sender.isDestroyed()) return
      try {
        sender.send(channel, payload)
      } catch {
        // isDestroyed 跟 send 之間 race 也吞掉
      }
    }
    try {
      await sidecar.call(msg.method, msg.params, safeSend)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      safeSend({ id: msg.callId, error: { code: 'IPC_ERROR', message }, final: true })
    }
  })

  // OS shell helpers — renderer 透過這些 IPC 開 / reveal 檔案。
  ipcMain.handle('shell:openPath', async (_e, path: string) => {
    const result = await shell.openPath(path)
    return result === '' ? null : result  // '' = success
  })
  ipcMain.handle('shell:revealInFinder', async (_e, path: string) => {
    shell.showItemInFolder(path)
    return null
  })

  // Folder picker — renderer 走 dialog.showOpenDialog (沒 fs 權限自己叫不到)
  ipcMain.handle('dialog:selectFolder', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory'],
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  // 檢查路徑是否實際存在 — RightSidebar / InlineFileCards 用,避免列出 model
  // 提到但檔已不存在的孤兒路徑。
  ipcMain.handle('fs:pathExists', async (_e, path: string) => {
    try {
      await fsPromises.access(path)
      return true
    } catch {
      return false
    }
  })

  // 單檔寫入(/export 打包 .zip 走這個)— 寫進 {targetDir ?? ~/Downloads}/{filename},
  // encoding='utf8' 寫文字、'base64' 寫二進位。同名加 -1 / -2 後綴避碰。
  ipcMain.handle(
    'dialog:saveFile',
    async (
      _e,
      filename: string,
      content: string,
      encoding: 'utf8' | 'base64',
      targetDir?: string,
    ) => {
      const base = targetDir && targetDir.trim() ? targetDir : app.getPath('downloads')
      await fsPromises.mkdir(base, { recursive: true })
      let dest = join(base, filename)
      let i = 1
      while (existsSync(dest)) {
        const { name, ext } = parse(filename)
        dest = join(base, `${name}-${i}${ext}`)
        i++
      }
      if (encoding === 'base64') {
        await fsPromises.writeFile(dest, Buffer.from(content, 'base64'))
      } else {
        await fsPromises.writeFile(dest, content, 'utf-8')
      }
      return dest
    },
  )

  // Export 資料夾(舊版 — 留著未用,未來可刪)— 一次寫 N 個檔到 {targetDir}/{bundleName}/。
  // files 結構:[{ relPath: 'sub/dir/file.ext', content: '...', encoding: 'utf8'|'base64' }]
  ipcMain.handle(
    'dialog:saveBundle',
    async (
      _e,
      bundleName: string,
      files: Array<{ relPath: string; content: string; encoding: 'utf8' | 'base64' }>,
      targetDir?: string,
    ) => {
      // 預設 ~/Downloads;caller 給了 targetDir(例:對話的 workspace_dir)就寫去那
      const base = targetDir && targetDir.trim() ? targetDir : app.getPath('downloads')
      // 確保 base dir 存在(workspace_dir 可能剛建還沒實體化)
      await fsPromises.mkdir(base, { recursive: true })
      let bundleDir = join(base, bundleName)
      let i = 1
      while (existsSync(bundleDir)) {
        bundleDir = join(base, `${bundleName}-${i}`)
        i++
      }
      await fsPromises.mkdir(bundleDir, { recursive: true })
      for (const f of files) {
        const fullPath = join(bundleDir, f.relPath)
        await fsPromises.mkdir(parse(fullPath).dir, { recursive: true })
        if (f.encoding === 'base64') {
          await fsPromises.writeFile(fullPath, Buffer.from(f.content, 'base64'))
        } else {
          await fsPromises.writeFile(fullPath, f.content, 'utf-8')
        }
      }
      return bundleDir
    },
  )

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
