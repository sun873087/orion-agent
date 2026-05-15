# apps/orion-cowork/tests/e2e/

跨 Electron renderer + main + sidecar 的 end-to-end 測試。**目前空,Phase 30 未實作**。

## 計畫範圍

啟動完整 Electron app,驗證:

- App 開窗,sidecar 啟動,renderer 收到 `sidecar.ready`
- 透過 IPC 觸發 `conversation.send`,renderer 顯示 streaming text
- Renderer 觸發 tool 呼叫(例如 Bash),收到 result
- Abort 流程
- 關閉時 sidecar 進程清乾淨

## 依賴

- **Headless Electron**:`xvfb`(Linux CI)或 `electron-builder` 的 spectron / playwright-electron
- `pytest`(Python 端)或 `vitest` + Playwright(TS 端)— 看選哪個生態系
- 真的 spawn Python sidecar(workspace `uv run`)

## 為何 Phase 30 沒做

- Headless Electron 在 CI 環境設定是頭痛源,光是穩定起來就要 3-5 天
- 屬於後續 phase scope

## 開工 checklist(留給後續 phase)

- [ ] 選 e2e 框架:Playwright Electron vs spectron(spectron 已棄用,推薦 Playwright)
- [ ] CI workflow 加 xvfb / headless display
- [ ] 第一個 happy-path test:啟 app → 看到 ready → 送 prompt → 看到 streaming
- [ ] Sidecar 殘留檢測:close window → assert no python process leaked

## 替代:單元級 e2e

短期內 sidecar 已有 `sidecar/tests/test_rpc.py`(子進程 stdio 測試)。renderer 跟
main 邏輯目前沒 unit test — 可以先用 Playwright 跑 vite dev server(不啟 Electron)
做 renderer 單元測試,等 Electron e2e 環境穩了再合併。
