import { defineConfig } from '@playwright/test'

/**
 * Cowork e2e config。
 *
 * 真實啟 Electron 進程,需要 GUI display(macOS / Windows native,Linux 需
 * xvfb)。預設 workers=1 — Electron 單例,不能平行。
 *
 * 跑法:
 * cd apps/orion-cowork && npm run test:e2e
 * 或從 root:make test-e2e-cowork
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  reporter: [['list']],
  use: {
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
})
