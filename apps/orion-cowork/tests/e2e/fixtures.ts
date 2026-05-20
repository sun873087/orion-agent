/**
 * Playwright Electron fixtures。
 *
 * 啟一個 Electron 進程,override sidecar 用 MockProvider(env var)。
 * 每個 test 一個獨立 tmp data dir,避免共用 ~/.orion/sessions/cowork.db。
 */

import { _electron as electron, test as base } from '@playwright/test'
import type { ElectronApplication, Page } from '@playwright/test'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

type Fixtures = {
  app: ElectronApplication
  page: Page
  dataDir: string
}

const repoRoot = resolve(__dirname, '..', '..', '..', '..')
const electronEntry = resolve(__dirname, '..', '..', 'dist', 'electron', 'main.js')

export const test = base.extend<Fixtures>({
  dataDir: async ({}, use) => {
    const dir = mkdtempSync(join(tmpdir(), 'cowork-e2e-'))
    await use(dir)
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch {
      /* ignore */
    }
  },

  app: async ({ dataDir }, use) => {
    const app = await electron.launch({
      args: [electronEntry],
      cwd: repoRoot,
      env: {
        ...process.env,
        NODE_ENV: 'development', // 用 vite :5174,要 dev server 跑著
        ORION_COWORK_DATA_DIR: dataDir, // 隔離 sidecar DB
        ORION_PROVIDER_OVERRIDE: 'mock', // sidecar 走 MockProvider,不打真 API
        ORION_MOCK_SCRIPT_JSON: JSON.stringify([{ text: 'mocked response' }]),
      },
      timeout: 30_000,
    })
    await use(app)
    await app.close()
  },

  page: async ({ app }, use) => {
    const page = await app.firstWindow()
    // Renderer 啟動先有 "initializing…",sidecar ready 後 sidebar 應出現
    await page.waitForLoadState('domcontentloaded')
    await use(page)
  },
})

export { expect } from '@playwright/test'
