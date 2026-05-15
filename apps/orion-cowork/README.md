# orion-cowork

PC 桌機應用 — Electron + React renderer + Python sidecar(直接 import orion-sdk)。

**Phase E PoC scope**:結構 + stdio 協定 + 最小 chat UI 跑通,證明三層架構運作正常。
production 打包(PyInstaller / electron-builder / 簽章 / auto-update)留待後續。

## 架構

```
┌──────────────────────────────────────────────────────────┐
│ Electron App                                              │
│                                                            │
│   Renderer (React)  ◀── IPC ──▶  Main process (Node TS)  │
│                                          │                 │
│                                          │ stdio JSON-RPC  │
│                                          ▼                 │
│                              Python sidecar (orion-sdk)   │
└──────────────────────────────────────────────────────────┘
```

- **Renderer** → `renderer/src/`:純 React,只透過 `window.agent.call(...)` 跟 main 講話
- **Main process** → `electron/`:`SidecarClient` 包 stdio,IPC handler 路由 renderer 訊息
- **Sidecar** → `sidecar/`:Python,獨立 workspace member(`orion-cowork-sidecar`),
  - `rpc.py` stdio loop + 並發 dispatch
  - `handlers.py` 接 SDK 的 `Conversation`
  - `streaming.py` SDK event → RPC frame

**不走 Chat API** — Cowork 是本機單機 app,直接用 SDK,沒有 HTTP/WS/JWT 那一套。

## Dev mode

需要:
- repo root 跑過 `uv sync` 跟 `npm install`
- `.env` 設好 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`

```bash
npm run dev -w @orion/cowork
```

`concurrently` 同時起 Vite renderer dev server(:5174)跟 Electron main,
Electron 載 `http://127.0.0.1:5174`,main 啟動時 spawn sidecar。

**已知限制(Phase E PoC)**:
- Electron 開窗實際跑需要 GUI 環境,headless CI 不適用
- API key 沒設會在第一次 `conversation.send` 時 RPC 回 error
- 沒有 conversation 持久化(關閉就丟)
- 沒有 abort UI(handler 有,UI 沒接)
- 工具 progress 沒顯示(只顯示 final result)
- 沒有美術 — Phase E renderer 是純 PoC

## Stdio JSON-RPC 協定

```
# Request (main → sidecar)
{"id": "req-1", "method": "conversation.send", "params": {"session_id": "...", "prompt": "..."}}

# Response frames (sidecar → main,可多筆,final:true 結尾)
{"id": "req-1", "event": "text_delta", "data": {"text": "Hello"}}
{"id": "req-1", "event": "tool_result", "data": {"tool_name": "Bash", "is_error": false, "text": "..."}}
{"id": "req-1", "event": "loop_terminated", "data": {"reason": "completed", "total_turns": 2}}
{"id": "req-1", "event": "done", "final": true}

# Notification (sidecar → main,無 id)
{"event": "sidecar.ready"}
{"event": "log", "level": "warn", "message": "..."}

# Error (final + error 欄位)
{"id": "req-1", "error": {"code": "MODEL_RATE_LIMIT", "message": "..."}, "final": true}
```

RPC method 對應在 `sidecar/src/orion_cowork_sidecar/handlers.py`。

## 測試

```bash
# Sidecar 單元測試(子進程拉起 sidecar,塞 stdin,讀 stdout)
cd apps/orion-cowork/sidecar && uv run pytest -q

# 手動 ping
echo '{"id":"1","method":"ping"}' | uv run --package orion-cowork-sidecar python -m orion_cowork_sidecar
```

## TODO(後續 phase)

- PyInstaller 打包 sidecar 到單一 binary,Electron app 內含
- electron-builder 跨平台 .app / .exe / .AppImage
- 完整 chat UI(不只是 PoC 級)
- 工具 progress 顯示
- Abort UI
- 會話持久化(本地 SQLite,跟 SDK 同 schema)
- MCP server 整合
- 多 provider / model 切換
- macOS notarization / Windows code signing
- Auto-update
