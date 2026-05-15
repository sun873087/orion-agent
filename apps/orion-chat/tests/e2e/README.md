# apps/orion-chat/tests/e2e/

跨 api + web 的 end-to-end 測試。**目前空,Phase 30 未實作**。

## 計畫範圍

啟動完整 stack(`uvicorn` + Postgres test container + web build artifact),
驗證:

- Login → JWT token → `/chat/stream/<sid>` WebSocket 連線
- 真送 prompt → 收到 streaming text → tool call → result
- Session resume(關 WS 重連,歷史可讀)
- Permission ask flow(WS 雙向訊息)

## 依賴

- `httpx` / `websockets`(WS client)
- `pytest-asyncio`
- `testcontainers` 或 docker-compose fixture(起 Postgres)
- web build artifact(`apps/orion-chat/web/dist/`)— 或測試只跑 api 層

## 為何 Phase 30 沒做

- 需先決定 CI 怎麼起 Postgres(現有 CI 無此設施)
- Web e2e 需 Playwright / Cypress 加入 dependency
- 屬於後續 phase scope,Phase 30 範圍是 monorepo 結構不是 test infra

## 開工 checklist(留給後續 phase)

- [ ] 決定 web 是否進 e2e scope(API-only e2e 範圍小很多)
- [ ] CI workflow 加 docker-compose / testcontainers
- [ ] 寫 fixture 自動 register user / 取 token
- [ ] 第一個 happy-path test:login + send + receive streaming
