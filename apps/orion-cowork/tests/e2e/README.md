# Cowork e2e tests

Playwright Electron 起完整 Cowork(renderer + main + sidecar)+ 透過 mock
provider override 跑 happy path,**不打真 LLM**(無成本)。

## 跑法

需要本機:
- `make install` 已跑過(`uv sync` + `npm install`)
- `npm install` 包含 `@playwright/test`(Phase 31-F 加進 `apps/orion-cowork`
  的 devDependencies — npm install 已自動裝)
- 第一次跑要 `npx playwright install`(下載 Playwright 用的 browsers,
  e2e 雖然不開 browser,但 Playwright runtime 需要)
- **GUI display**:macOS / Windows native 直接跑;Linux CI 需 `xvfb-run`
- Renderer:dev mode 需要 vite dev server(:5174)同步跑

兩個 terminal:

```bash
# Terminal 1:vite renderer dev
npm run dev:renderer -w @orion/cowork

# Terminal 2:跑 e2e
npm run test:e2e -w @orion/cowork
# 或從 root
make test-e2e-cowork
```

## Mock provider 注入

`fixtures.ts` 啟 Electron 時帶 env:

- `ORION_PROVIDER_OVERRIDE=mock` — sidecar `__main__.py` 看到後呼
  `set_test_provider_factory()`,所有 LLM call 都走 fake
- `ORION_MOCK_SCRIPT_JSON='[{"text":"hi"}, ...]'` — scripted turns
- `ORION_COWORK_DATA_DIR=/tmp/cowork-e2e-xxx` — 隔離 sessions.db,test 互不污染

## 已有 specs

- `smoke.spec.ts` — app 啟動 / sidebar New chat 出現 / 多按 New chat 不建空 session

## 留下 phase 補

- 完整 chat flow:send prompt → 看到 streaming text → tool call → result
- Abort mid-flight UI
- Settings panel 切換 theme / model 後再 send
- MCP server 顯示 / reconnect
- Cross-restart persistence(open app → send → close → reopen → 見 history)

## Headless mode

Playwright Electron 不支援完全 headless(Electron 本身需要 display)。Linux CI
得 `xvfb-run`:

```bash
xvfb-run --auto-servernum npm run test:e2e -w @orion/cowork
```

macOS / Windows CI runner 有實體 display 不用額外設定。

## 為何沒在 main test 套件跑

預設 `make test` 不跑這個(避免每次測試都彈 Electron 窗)。要 opt-in
`make test-e2e-cowork`。
