# Phase 31-D:Cowork local persistence + MCP

## 速覽

- **預計時程**:1 週
- **前置 Phase**:31-C(UI complete)
- **狀態**:📝 spec only,**未實作**
- **目標**:Cowork 對話跨 app restart 保留 + 連接 MCP server + 多 provider 切換真正 functional。

## 1. 本機 SQLite session 持久化

Cowork 用 `orion-sdk` 的 storage 層,但放本機 SQLite(不是 Postgres):

```
~/.orion-cowork/                                # macOS / Linux
%LOCALAPPDATA%\Orion Cowork\                     # Windows
├── sessions.db                                  # SQLite
└── sessions/<uuid>/
    ├── transcript.jsonl
    ├── tool-results/
    └── file-history/
```

### 1.1 啟動流程

```python
# sidecar/handlers.py
async def _ensure_db(self):
    db_url = f"sqlite+aiosqlite:///{cowork_data_dir()}/sessions.db"
    self.engine = create_db_engine(db_url)
    await init_db(self.engine)  # 跑 orion-sdk migrations
```

### 1.2 跟 SDK schema 對齊

直接用 SDK 既有 `User` / `Session` / `Message` 表,但 Cowork single-user 模式:

- 啟動時建 dummy user(id 固定 `cowork-local`,username `local`)
- 所有 session 掛在這個 user 下
- `Conversation` 用 `DbSessionManager` 替代 in-memory

### 1.3 RPC method 升級

| Method | 行為改動 |
|---|---|
| `conversation.create` | 寫 DB,回傳 session_id |
| `conversation.list` | 從 DB query 全部 session(by user_id="cowork-local") |
| `conversation.resume` | 從 DB 載入 messages,還原 Conversation |
| `conversation.delete` | DELETE FROM sessions WHERE id = ? CASCADE |

## 2. MCP server 整合

### 2.1 配置

Cowork **不**讀 `~/.orion/mcp.json`(那是 CLI / chat-api 共用的),用自己:

```
~/.orion-cowork/mcp.json
```

格式同 SDK 既有(`mcpServers: {...}`)。

### 2.2 UI

Settings panel 加 "MCP Servers" 區:

- 列出已配置 server + 狀態(connected / failed / disabled)
- "Add server" 按鈕開 dialog 填 transport / command / args
- per-server toggle 啟用/停用

### 2.3 OAuth flow

Cowork 不能像 CLI 用 localhost callback(會被 OS firewall 擋)。改:

- 用 Electron 內建 BrowserWindow 開 OAuth URL
- 攔截 redirect URL(`webContents.on('will-redirect', ...)`)
- 抽 code → 換 token → 存 keyring

詳見 `electron-oauth-helper`(npm package)pattern。

### 2.4 任務

- [ ] sidecar `McpManager` 啟動讀 `~/.orion-cowork/mcp.json`
- [ ] 新 RPC method `mcp.list` / `mcp.add` / `mcp.remove` / `mcp.toggle`
- [ ] OAuth flow 改 Electron BrowserWindow 版本
- [ ] Settings UI 加 MCP server 列表

## 3. Multi-provider / model 切換

### 3.1 UI

Header 加 ModelPicker(類似 Cursor / Claude Code):

```
[ anthropic / claude-sonnet-4-6  ▾ ]
   ├─ Anthropic
   │   ├─ claude-opus-4-7
   │   ├─ claude-sonnet-4-6
   │   ├─ claude-haiku-4-5
   ├─ OpenAI
   │   ├─ gpt-5
   │   ├─ gpt-4o
   │   ├─ gpt-4o-mini
   └─ ⚙ Configure...
```

### 3.2 切換語意

- **同 conversation 內換 model**:從下一個 turn 起用新 model(不影響歷史)
- **新 conversation**:預設用上次選的 model
- 換 provider:必須有對應 API key(沒填則灰掉)

### 3.3 任務

- [ ] orion-model 暴露 `list_models(provider)` API 列當前可用 model
- [ ] sidecar 新 RPC method `conversation.set_model(session_id, provider, model)`
- [ ] UI ModelPicker 元件
- [ ] Sidecar 同步 model 設定到 `Conversation.provider`(可能要 hot-swap provider object)

### 3.4 Hot-swap caveat

`Conversation.provider` 是 dataclass field,直接設值技術上可,但要小心:
- system prompt 內若有 model-specific 段(reasoning effort),要重組
- cache breakpoint 要失效(不同 model 不能共用 cache)

簡化版本:同 conversation 內換 model 視為新 conversation 的開始(append 一個 "[model switched to X]" system note,後續用新 cache)。

## 4. 風險

| 風險 | 緩解 |
|---|---|
| Migration 跑在 user 機器,失敗炸 | 加 try/except + 顯示 error dialog + fallback to fresh DB |
| 大歷史 conversation load 慢 | 用 storage/resume 的 lazy 機制(transcript 只 metadata,messages 按需 load)|
| MCP server 啟動慢拖慢 app 啟動 | MCP 連線改 background task,不 block UI |
| OAuth 跨網域問題(provider 拒 BrowserWindow user-agent) | 改 default user-agent 為 Electron 標準;最壞 case fallback 到「複製 URL 到瀏覽器」 |
| Model 切換破壞既有 cache | 預期內,計入成本 |

## 5. 驗收

- [ ] 開 app → 看到上次的 conversation 列表 → 點 → 看到歷史訊息
- [ ] 關 app → 重開 → 對話完整保留
- [ ] Settings → 加一個 MCP server(filesystem)→ 重啟 → LLM 看得到 filesystem tools
- [ ] Model picker 切到 OpenAI gpt-5 → 下個 turn 用新 model
- [ ] 同 conversation 跨 model 切換不爆

## 6. 完成後

Phase 31-D 完成 = Track 1(Cowork ship-readiness)結束。Cowork **真正可用**。
