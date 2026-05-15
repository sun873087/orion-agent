# Phase 30-E:Cowork(Electron + Python sidecar)

## 速覽

- **預計時程**:1-2 週(全職)
- **前置 Phase**:30-C(orion-sdk 已獨立成 package)
- **狀態**:📝 spec only,**未實作**
- **目標**:新建 PC 本地桌機應用 Cowork。Electron + React renderer + Python sidecar(直接 import `orion-sdk`),透過 stdio JSON-RPC 通訊。**完全不經過 Chat API**

## 1. 為何不走 Chat API

Cowork 是 PC 本地單機 app — 單一使用者、單一機器、本機檔案完整存取。Chat API 為「跨網路 / 多使用者」設計的東西(JWT auth、CORS、多 session、HTTP overhead、CSRF 防護)Cowork 一個都不需要。讓 Cowork 走 chat-api 等於要它先打開 HTTP server、發 token 給自己、再連回來 — 沒有意義。

**正確設計**:Cowork 是平行於 CLI / Chat API 的 SDK consumer,跟 SDK 同進程系(Electron main → spawn python sidecar → import orion-sdk)。

## 2. 架構

```
┌──────────────────────────────────────────────────────────────┐
│ Electron Application                                          │
│                                                                │
│  ┌────────────────────┐         ┌────────────────────────┐   │
│  │ Renderer (React)   │  IPC    │ Main Process (Node TS) │   │
│  │ - chat UI          │ ◀────▶  │ - window 管理            │   │
│  │ - 獨立重寫(不複用 │         │ - spawn / kill sidecar  │   │
│  │   chat/web)        │         │ - 轉發 IPC ↔ stdio      │   │
│  └────────────────────┘         └────────────┬───────────┘   │
│                                                │ stdio        │
│                                                ▼              │
│                                  ┌────────────────────────┐   │
│                                  │ Python Sidecar          │   │
│                                  │ - import orion_sdk      │   │
│                                  │ - stdio JSON-RPC loop   │   │
│                                  │ - 跑 Conversation       │   │
│                                  └────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

**為何用 stdio 而不是 HTTP/WS**:
- 沒有 port 衝突
- 沒有 auth / CORS 廢話
- 啟動快(spawn 一個 process 就好)
- 安全 — 沒有 socket 對外暴露
- Electron child_process API 原生支援 stdio,簡單

## 3. 目錄結構

```
apps/orion-cowork/
├── package.json                ← Electron + React + Vite
├── tsconfig.json
├── electron-builder.yml        (Phase E 不打包,留位置)
├── vite.config.ts              (renderer 開發 dev server)
├── electron/                   ← main process (Node TS)
│   ├── main.ts                 ← BrowserWindow + lifecycle
│   ├── sidecar.ts              ← spawn / kill / 重啟 python sidecar
│   ├── ipc.ts                  ← renderer ↔ main IPC handlers
│   └── preload.ts              ← 暴露 typed API 給 renderer
├── renderer/                   ← React UI(獨立重寫,不複用 chat/web)
│   ├── index.html
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api/                ← 透過 preload 跟 main 講話
│   │   │   └── agent.ts
│   │   └── components/
│   │       └── (UI 元件,Phase E 不要求完整,放 placeholder)
│   └── tsconfig.json
└── sidecar/                    ← Python sidecar
    ├── pyproject.toml
    ├── src/orion_cowork_sidecar/
    │   ├── __main__.py         ← `python -m orion_cowork_sidecar`
    │   ├── rpc.py              ← stdio JSON-RPC loop
    │   ├── handlers.py         ← rpc method → SDK 呼叫
    │   └── streaming.py        ← Conversation event → JSON frame
    └── tests/
```

## 4. stdio JSON-RPC 協定

### 4.1 Wire format

每行一個 JSON object(newline-delimited),`\n` 分隔。Electron main 跟 sidecar 雙向都用同一格式。

**Request**(main → sidecar):

```json
{"id": "req-1", "method": "conversation.send", "params": {
  "session_id": "uuid",
  "prompt": "...",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6"
}}
```

**Response**(sidecar → main):一個 request 可能對應**多個** response(streaming),最後一個 `final: true`。

```json
{"id": "req-1", "event": "text_delta", "data": {"text": "Hello"}}
{"id": "req-1", "event": "text_delta", "data": {"text": " world"}}
{"id": "req-1", "event": "tool_progress", "data": {"tool": "Bash", "stage": "starting"}}
{"id": "req-1", "event": "tool_result", "data": {"tool": "Bash", "result": "..."}}
{"id": "req-1", "event": "turn_complete", "final": true}
```

**錯誤**:

```json
{"id": "req-1", "error": {"code": "MODEL_RATE_LIMIT", "message": "..."}, "final": true}
```

**Notification**(sidecar → main 主動,沒 request id):

```json
{"event": "sidecar.ready"}
{"event": "log", "level": "warn", "message": "..."}
```

### 4.2 RPC methods(最小集,Phase E 範圍)

| Method | 用途 |
|---|---|
| `ping` | 健康檢查 |
| `conversation.create` | 新建 Conversation,回 session_id |
| `conversation.send` | 送 prompt,streaming 回事件 |
| `conversation.resume` | 從 session_id 載入舊對話 |
| `conversation.abort` | 中止當前 turn |
| `conversation.list` | 列本機所有 session |
| `shutdown` | sidecar 優雅關閉 |

更多(memory / settings / MCP / sandbox / multi-agent)留給後續 phase。Phase E 只要 PoC 通就好。

### 4.3 Sidecar 對應到 SDK 的 mapping

```python
# apps/orion-cowork/sidecar/src/orion_cowork_sidecar/handlers.py
from orion_sdk import Conversation, AgentContext, load_feature_flags
from orion_model import get_provider

class Handlers:
    def __init__(self):
        self._conversations: dict[str, Conversation] = {}

    async def conversation_send(self, session_id, prompt, provider, model):
        ctx = AgentContext(feature_flags=load_feature_flags(), user_id="cowork-local")
        conv = self._conversations[session_id]
        async for event in conv.send(prompt, ctx=ctx):
            yield _to_rpc_event(event)
```

事件 → RPC frame 的對應跟 `apps/orion-cli/src/orion_cli/__main__.py` 的 `_render` 一樣,只是輸出形式從「印終端」換成「寫 stdout JSON」。

## 5. 任務拆解

### 5.1 骨架

- [ ] `mkdir -p apps/orion-cowork/{electron,renderer/src,sidecar/src/orion_cowork_sidecar}`
- [ ] 寫 `apps/orion-cowork/package.json`(electron + vite + react)
- [ ] 寫 `apps/orion-cowork/sidecar/pyproject.toml`(dep: `orion-sdk`,workspace)
- [ ] root `pyproject.toml` 加 `apps/orion-cowork/sidecar` 到 members
- [ ] root `package.json` 加 `apps/orion-cowork` 到 workspaces
- [ ] `uv sync` + `npm install` 通

### 5.2 Sidecar(先做,可獨立測)

- [ ] 寫 `rpc.py`:async stdio loop,讀一行 parse JSON,dispatch 到 handler
- [ ] 寫 `handlers.py`:`ping` / `conversation.create` / `conversation.send` 三個 minimum methods
- [ ] 寫 `streaming.py`:把 SDK 的 `AssistantTextDelta` / `ToolProgressUpdate` 等事件轉成 RPC frame
- [ ] 寫 `__main__.py`:`python -m orion_cowork_sidecar` 啟動 RPC loop
- [ ] 手動測:`echo '{"id":"1","method":"ping"}' | python -m orion_cowork_sidecar` 回 pong

### 5.3 Electron main + preload

- [ ] `electron/sidecar.ts`:spawn `uv run --package orion-cowork-sidecar python -m orion_cowork_sidecar`,管 stdin/stdout
- [ ] `electron/main.ts`:啟動 BrowserWindow + 啟 sidecar
- [ ] `electron/preload.ts`:用 `contextBridge.exposeInMainWorld('agent', { send, abort, ... })`,renderer 端可呼叫
- [ ] `electron/ipc.ts`:IPC handler 收 renderer 訊息,轉成 stdio request 送 sidecar,streaming response 推回 renderer

### 5.4 Renderer

- [ ] React + Vite + Tailwind(可選)
- [ ] 一個極簡 ChatUI:輸入框 + message list + streaming token render
- [ ] 用 `window.agent.send(prompt, onEvent)` 呼叫 main process
- [ ] 不複用 `apps/orion-chat/web/` 元件 — 你已確定獨立重寫

### 5.5 Dev mode

- [ ] `npm run dev`(在 `apps/orion-cowork/`)同時起 Vite renderer dev server + Electron main(`concurrently`)
- [ ] Electron main 在 dev mode 載 `http://localhost:5173`,production 載 `dist/index.html`
- [ ] Sidecar 在 dev mode 走 `uv run`(吃 workspace),production 走打包後的 PyInstaller binary

### 5.6 整合驗證

- [ ] Electron 開窗,renderer 顯示 chat UI
- [ ] 輸入 prompt,看到 streaming text 一字一字出現
- [ ] 觸發 tool 呼叫(例如「列出 /etc」),看到 Bash tool progress + result
- [ ] 關 Electron 窗,sidecar process 也優雅退出

## 6. 不在 Phase E scope 內

明確留給後續 phase:

- **PyInstaller 打包成單一 .app / .exe**(production distribution)— 另開 phase
- **Auto-update**(Squirrel / electron-updater)— 另開 phase
- **macOS notarization / Windows code signing**
- **多視窗 / 分屏 / 系統托盤** — UI 進階特性
- **本地檔案 drag & drop**、OS 通知整合
- **完整 UI 設計**(Phase E 的 renderer 是 PoC 級,只證明 stdio agent loop 跑得起來)
- **權限提示對話框**(SDK 的 permission policy 整合到 GUI)— Phase E 用 always_allow
- **MCP servers 整合**(雖然 SDK 有,Cowork 一開始不啟用)
- **多 provider / model 切換 UI**

## 7. 風險與緩解

| 風險 | 嚴重度 | 緩解 |
|---|---|---|
| Sidecar process 死掉,renderer 卡住 | 高 | main 監聽 sidecar `exit` event,自動重啟 + 通知 renderer;sidecar 寫 heartbeat |
| stdio buffer 滿(大 tool result)導致 deadline | 中 | sidecar 用 line-buffered stdout;大 payload 改 base64 + 拆 chunk;極大者(>1MB)走 disk + 傳 file path |
| Python 路徑找不到(end-user 機器沒 uv / python) | 高 | dev mode 用 uv;production 用 PyInstaller 把 Python runtime 打進去(Phase E 之後)— Phase E dev 階段要求 dev 機器有 uv 即可 |
| Electron context isolation 設不對,IPC 漏 | 中 | 嚴格用 contextBridge,preload 不暴露 ipcRenderer 原生 |
| Renderer 跟 main 之間 streaming 卡頓 | 中 | main 對每個 stdout line 立刻 `webContents.send` 推 renderer,別 batch |
| SDK `Conversation` 是 async generator,RPC 怎麼包 | 中 | RPC server 每收一個 method call,起一個 task 跑 generator,每個 yield 寫一行 stdout |
| 多個 in-flight requests 互相干擾 | 中 | RPC frame 有 `id`,sidecar 每個 request 開獨立 asyncio task,response 帶 id 給 main 路由 |
| Windows path / line-ending 問題 | 中 | sidecar 寫 stdout 強制 `\n`(不要 `\r\n`),main 端 split 用 `\n` |

## 8. 為何用 JSON-RPC 而不是更輕量的格式(如 ndjson / protobuf)

- **可讀性**:dev 階段 stdout 可直接眼看
- **不用工具鏈**:不需要 .proto compile,Python / TS 內建 JSON
- **未來換 transport 不影響協定**:若以後想換 unix socket / named pipe,協定不動

protobuf / msgpack 等到 sidecar 流量爆大才考慮。

## 9. 驗收

- [ ] `cd apps/orion-cowork && npm run dev` Electron 開窗
- [ ] Renderer chat UI 可輸入 prompt
- [ ] Streaming text 一字一字顯示
- [ ] 至少一個 tool(Bash)能執行並回 result 給 renderer
- [ ] 關窗時 sidecar 進程清乾淨(`ps aux | grep orion_cowork_sidecar` 沒殭屍)
- [ ] Sidecar 單獨可測:`echo '{"id":"1","method":"ping"}' | python -m orion_cowork_sidecar` 回正確 pong frame
- [ ] Sidecar tests 跑得起來(`uv run --package orion-cowork-sidecar pytest`)

## 10. 完成後的狀態

```
orion-agent/
├── pyproject.toml              members 加上 apps/orion-cowork/sidecar
├── package.json                workspaces 加上 apps/orion-cowork
├── apps/
│   ├── orion-cli/
│   ├── orion-chat/
│   └── orion-cowork/           ★ 新
│       ├── package.json
│       ├── electron/
│       │   ├── main.ts
│       │   ├── sidecar.ts
│       │   ├── ipc.ts
│       │   └── preload.ts
│       ├── renderer/
│       │   ├── index.html
│       │   └── src/
│       │       ├── App.tsx
│       │       ├── api/agent.ts
│       │       └── components/
│       └── sidecar/
│           ├── pyproject.toml
│           ├── src/orion_cowork_sidecar/
│           │   ├── __main__.py
│           │   ├── rpc.py
│           │   ├── handlers.py
│           │   └── streaming.py
│           └── tests/
└── ...
```

## 11. 下一步

Phase E 跑通了,Phase F(收尾)。Cowork production 打包 / UI 完善另開 phase。
