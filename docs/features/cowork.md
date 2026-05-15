# Cowork

PC 本地桌機 app。**不**連 chat-api,Electron main process spawn 一個 Python sidecar 直接 `import orion_sdk` 跑 agent loop。

**實作位置**:`apps/orion-cowork/`

```
apps/orion-cowork/
├── electron/        TS — main process(spawn sidecar、IPC handler、BrowserWindow)
├── renderer/        TS — React UI(獨立重寫,不複用 chat/web)
└── sidecar/         Python — orion-cowork-sidecar workspace member
```

## 三層架構

```
┌──────────────────────────────────────────────────────────┐
│ Electron app                                              │
│                                                            │
│   Renderer (React)  ◀── IPC ──▶  Main (Electron Node TS) │
│                                          │                 │
│                                          │ stdio JSON-RPC  │
│                                          ▼                 │
│                              Python sidecar               │
│                              (import orion_sdk)           │
└──────────────────────────────────────────────────────────┘
```

## Stdio JSON-RPC 協定

每行一個 JSON object,newline-delimited。完整定義在 `apps/orion-cowork/sidecar/src/orion_cowork_sidecar/rpc.py`。

### Request(main → sidecar)

```json
{"id": "req-1", "method": "conversation.send", "params": {
  "session_id": "uuid-here",
  "prompt": "..."
}}
```

### Response frames(sidecar → main,可多筆)

```json
{"id": "req-1", "event": "text_delta", "data": {"text": "Hello"}}
{"id": "req-1", "event": "tool_result", "data": {"tool_name": "Bash", "is_error": false, "text": "..."}}
{"id": "req-1", "event": "loop_terminated", "data": {"reason": "end_turn", "total_turns": 2}}
{"id": "req-1", "event": "done", "final": true}
```

### Notification(sidecar → main,無 id)

```json
{"event": "sidecar.ready"}
{"event": "log", "level": "warn", "message": "..."}
```

### Error

```json
{"id": "req-1", "error": {"code": "VALUEERROR", "message": "..."}, "final": true}
```

## 支援的 RPC methods(Phase E PoC scope)

| Method | params | 用途 |
|---|---|---|
| `ping` | (none) | 健康檢查 → `pong` |
| `conversation.create` | `provider`, `model` | 新建 Conversation,回 `session_id` |
| `conversation.send` | `session_id`, `prompt` | 送 prompt,streaming 回 events |
| `conversation.abort` | `session_id` | 中止當前 turn(set abort_event) |

未實作(留給後續 phase):`conversation.resume` / `conversation.list` / memory / settings / MCP / multi-agent 等。

## Renderer side

```typescript
// renderer/src/api/agent.ts
await window.agent.call(
  'conversation.send',
  { session_id, prompt: 'hello' },
  (frame) => {
    if (frame.event === 'text_delta') {
      // append frame.data.text to UI
    }
  }
)
```

`window.agent` 由 `electron/preload.ts` 透過 `contextBridge.exposeInMainWorld` 暴露,renderer 無法直接接觸 ipcRenderer 原生 API(符合 Electron context isolation)。

## Main process job

1. App ready → `SidecarClient.start()` spawn Python 進程
2. 等 `sidecar.ready` notification → 才開 BrowserWindow
3. Renderer 透過 IPC 送 `agent:call` → main 轉 stdio request 給 sidecar
4. Sidecar 每筆 stdout line → main 解析 → `webContents.send` 推 renderer
5. App quit → `SidecarClient.dispose()` 關 stdin (EOF) → sidecar graceful 退出(3 秒 timeout 後 SIGTERM)

## Sidecar 生命週期管理

`sidecar.ts:SidecarClient`:
- spawn 時用 `uv run --package orion-cowork-sidecar python -m orion_cowork_sidecar`(dev mode)
- production 改打 PyInstaller binary(尚未實作)
- 監聽 child exit event,死掉時 reject 所有 pending requests + reset state
- buffer 處理:stdout 可能一次拿到多行 / 半行,split `\n` 處理 boundary

## 為何不連 chat-api

詳見 [`../architecture/design-decisions.md`](../architecture/design-decisions.md) §3。簡述:Cowork 是本機單機,不需要 JWT / CORS / HTTP / 多 user 那一套。

## Phase E 已實作 / 未實作

**已實作**(Phase E PoC):
- ✅ Sidecar 3 個 RPC method(ping / create / send + abort)
- ✅ Sidecar 7 個 unit test(子進程拉起 sidecar 塞 stdin 讀 stdout)
- ✅ Electron main + preload + BrowserWindow
- ✅ Renderer 極簡 chat UI
- ✅ Dev mode(`npm run dev -w @orion/cowork`)

**未實作**:
- ❌ PyInstaller 打包 sidecar → single binary
- ❌ electron-builder 跨平台 .app / .exe / .AppImage
- ❌ macOS notarization / Windows code signing
- ❌ Auto-update(electron-updater)
- ❌ 完整 UI(目前是 PoC 級)
- ❌ 工具 progress 顯示 / abort UI
- ❌ 會話持久化(關閉就丟)
- ❌ MCP server 整合
- ❌ Multi-provider / model 切換 UI
- ❌ E2e 測試(headless Electron 環境)

詳見 `apps/orion-cowork/tests/e2e/README.md` 跟 [`../roadmap/`](../roadmap/)。

## 限制

- 大 tool result 走 stdio:目前無 cap,超大 payload 會塞滿 buffer。將來考慮:>1MB 走 disk + 傳 file path
- Windows 路徑 / line-ending:sidecar 寫 stdout 強制 `\n`(不 `\r\n`),main 端 split `\n`
- 多 in-flight requests:每個 request 帶 id,sidecar 開獨立 asyncio task,response 帶 id 路由給對應 handler
- 不重啟 sidecar:目前 sidecar 死掉只 reject 現有 requests,renderer 看到 error,需要 user manual reload。Production 該加自動重啟。

## 相關

- [`../architecture/packages.md`](../architecture/packages.md) §orion-cowork — 結構速覽
- [agent-loop.md](./agent-loop.md) — sidecar 內 SDK 怎麼跑
- [`../roadmap/`](../roadmap/) — 接下來要做什麼
