# Phase 31-F:Cowork e2e infra

## 速覽

- **預計時程**:1 週
- **前置 Phase**:31-D(Cowork persistence + UI 完整,才有 flow 可測)
- **狀態**:📝 spec only,**未實作**(目前只有 `apps/orion-cowork/tests/e2e/README.md` placeholder)
- **目標**:headless Electron e2e — 啟動完整 Cowork(renderer + main + sidecar),透過 Playwright 操作 UI,驗證主要 flow。

## 1. 為何難

跟 chat-api e2e 不同,Cowork e2e 要:

- 啟動真 Electron app(headless 但 GUI 程序仍在跑)
- Playwright connect 到 Electron renderer page
- Sidecar(Python)也要跟著起 + 對話得通
- CI 需要 xvfb(Linux 虛擬 display)或 macOS / Windows runner(實體 display)

Headless Electron 是業界知名痛點,但 Phase 31-D 完成後 Cowork 有完整 flow 可測,值得做。

## 2. 範圍

### 2.1 In scope

- 啟 Cowork(dev mode,vite dev server + Electron + sidecar)
- Playwright Electron API 操作 renderer
- MockProvider 注入(env var override,同 chat-api e2e)
- happy-path:開窗 → 看到 ready → 輸入 prompt → 看到 streaming → 看到 tool result
- 對話持久化:關 app → 重開 → 看到歷史

### 2.2 Out of scope

- 簽章 / notarization 流程的測試(那是 Phase 31-B 自己驗)
- Auto-update 流程
- 多視窗 / 系統托盤
- 真 LLM call(MockProvider)
- 跨 OS native widget(Playwright 處理基本 widget,OS-specific 細節留給 manual QA)

## 3. 任務拆解

### 3.1 Playwright Electron setup

```bash
npm install -D @playwright/test playwright
```

`apps/orion-cowork/playwright.config.ts`:

```typescript
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  use: { trace: 'on-first-retry' },
  workers: 1,  // Electron 單實例,不能平行
})
```

### 3.2 Fixture:啟 Cowork

```typescript
// tests/e2e/fixtures.ts
import { test as base, _electron, Page, ElectronApplication } from '@playwright/test'

type Fixtures = { app: ElectronApplication; page: Page }

export const test = base.extend<Fixtures>({
  app: async ({}, use) => {
    const app = await _electron.launch({
      args: ['./dist/electron/main.js'],
      env: {
        ...process.env,
        NODE_ENV: 'test',
        ORION_PROVIDER_OVERRIDE: 'mock',
        ORION_COWORK_DATA_DIR: '/tmp/cowork-e2e-' + Date.now(),  // 隔離 user data
      },
    })
    await use(app)
    await app.close()
  },
  page: async ({ app }, use) => {
    const page = await app.firstWindow()
    await page.waitForSelector('text=ready', { timeout: 10000 })
    await use(page)
  },
})
```

### 3.3 MockProvider 注入到 sidecar

sidecar 收 `ORION_PROVIDER_OVERRIDE=mock` env var → `handlers.py` 內 `get_provider()` 改回 MockProvider,scripted turns 從另一個 env var `ORION_MOCK_SCRIPT_JSON` 讀。

```python
def _get_provider_for_test():
    if os.getenv("ORION_PROVIDER_OVERRIDE") == "mock":
        script = json.loads(os.getenv("ORION_MOCK_SCRIPT_JSON", "[]"))
        return MockProvider(turns=[MockTurn(**t) for t in script])
    return get_provider(...)
```

Test 透過 env var 設定 scripted turns。

### 3.4 happy-path test

```typescript
import { test } from './fixtures'
import { expect } from '@playwright/test'

test('user sends prompt and sees streaming response', async ({ page }) => {
  await page.fill('input[placeholder*="message"]', 'hello')
  await page.click('button:has-text("Send")')

  await expect(page.locator('[data-role="assistant"]').first()).toContainText('mocked response')
  await expect(page.locator('text=Sandboxed')).toBeVisible()  // tool result
})
```

### 3.5 持久化 test

```typescript
test('conversation persists across app restart', async ({ app, page }) => {
  await sendPrompt(page, 'remember this')
  const sid = await getCurrentSessionId(page)

  await app.close()

  const app2 = await _electron.launch({ args: [...], env: { ORION_COWORK_DATA_DIR: '...' } })
  const page2 = await app2.firstWindow()
  await page2.click(`[data-session-id="${sid}"]`)
  await expect(page2.locator('text=remember this')).toBeVisible()
  await app2.close()
})
```

### 3.6 CI 環境

Linux runner 需要 xvfb:

```yaml
- run: sudo apt-get install -y xvfb
- run: xvfb-run --auto-servernum npm run test-e2e -w @orion/cowork
```

macOS / Windows runners 直接跑(有實體 display)。

### 3.7 Makefile target

```makefile
test-e2e-cowork:
	npm run test:e2e -w @orion/cowork
```

`apps/orion-cowork/package.json`:
```json
"scripts": {
  "test:e2e": "playwright test"
}
```

## 4. 風險

| 風險 | 緩解 |
|---|---|
| Headless Electron 啟動 flaky(5-10% 失敗率業界常態) | retry on failure;CI 設 2 次 retry |
| Sidecar process 殘留 | fixture teardown 確保 SIGKILL sidecar |
| xvfb 在 macOS / Windows CI 無 → 需各自 runner | matrix:linux-xvfb / macos-direct / windows-direct |
| Playwright Electron API 不穩(Electron 版本相依) | pin electron + playwright 版本 |
| Mock provider 跟真 provider 行為差太多,測過不代表 production 過 | 接受 — e2e 驗 flow,不驗 LLM behavior |

## 5. 驗收

- [ ] `make test-e2e-cowork` local 跑得起來,3+ test 全綠
- [ ] CI 各 OS runner 跑得起來(若有 CI)
- [ ] 跑時間 < 2 分鐘(Electron 啟動 ~3s/test,test 3-5 個)

## 6. 完成後

Phase 31-F 完成 = Cowork 有產線 confidence。Track 2 結束。
