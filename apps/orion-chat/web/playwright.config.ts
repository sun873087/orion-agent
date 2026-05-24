import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

/**
 * Web 整合測試:真實啟 chat-api(MockProvider,無 API key)+ vite dev,
 * 用 chromium 驅動完整 UI 流程(auth / CRUD / i18n / 各 phase)。
 *
 * - API 走 ORION_PROVIDER=mock → 零 secret、deterministic、不打真 LLM。
 *   牽涉 LLM 內容的斷言留在 pytest;這裡測 UI + REST 整合。
 * - 每 run 一個 tmp dir(DB + users/skills/roles 全隔離),不污染 ~/.orion。
 * - 跑法:cd apps/orion-chat/web && npm run test:e2e
 */

const API_PORT = 8799
const WEB_PORT = 4823
const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../..',
)
const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'orion-pw-'))

const apiEnv: Record<string, string> = {
  ORION_PROVIDER: 'mock',
  ORION_DB_URL: `sqlite+aiosqlite:///${path.join(runDir, 'test.db')}`,
  ORION_DB_AUTO_CREATE: '1',
  ORION_JWT_SECRET: 'pw-e2e-secret',
  ORION_USERS_DIR: path.join(runDir, 'users'),
  ORION_USER_SKILLS_DIR: path.join(runDir, 'users'),
  ORION_USER_ROLES_DIR: path.join(runDir, 'users'),
  ORION_SKILLS_DIR: path.join(runDir, 'system_skills'),
}

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `uv run --package orion-chat-api uvicorn orion_chat_api.app:create_app --factory --host 127.0.0.1 --port ${API_PORT}`,
      cwd: repoRoot,
      env: apiEnv,
      port: API_PORT,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
      env: { ORION_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      port: WEB_PORT,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
