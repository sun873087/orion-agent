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

## 支援的 RPC methods

> **狀態**:Phase E PoC 起,Phase 31 後已從 4 個 method 擴張到 ~50+,涵蓋對話 / 專案 /
> 排程 / 技能 / 記憶 / MCP / STT / 權限。完整列表見
> `apps/orion-cowork/sidecar/src/orion_cowork_sidecar/handlers.py:methods()`。

| 類別 | Methods |
|---|---|
| **Conversation** | `conversation.{create,send,abort,list,search,delete,messages,attachment,regenerate,truncate,fork,rename,set_starred,stats,context_breakdown,compact,get_workspace,set_workspace,set_project,tool_approval,ask_user_reply,set_permission_mode,get_budget,set_budget,set_plan_mode,plan_approve,plan_reject,plan_status}` |
| **Project** | `project.{list,get,create,update,delete}` |
| **Memory** | `memory.{list,get,write,delete}` |
| **Skill** | `skill.{list,get,write,import_folder,delete}` |
| **Schedule / Loop**(Phase 31-G) | `schedule.{list,get,write,delete,run_now}` |
| **Prefs / Tools** | `prefs.{get_all,set}`、`tools.list_builtin` |
| **Permissions** | `permissions.{get,set}` |
| **MCP** | `mcp.{list,reconnect,config_list,config_upsert}` |
| **STT**(Phase 31-D) | `stt.{transcribe,status}` |
| **TTS**(Phase 31-T) | `tts.{synthesize,status}` |
| **Models** | `models.list` |

Notifications(sidecar 主動 push,無 `id`):
- `sidecar.ready` — sidecar 啟動完成
- `scheduler.fired` — 排程 / loop 觸發完成(renderer refresh sessions + 對齊 sidebar)
- `plan_mode.{entered,exited,awaiting_approval,approved,rejected}` — Phase 31-J Plan Mode 狀態轉移
- `budget.exceeded` — Phase 31-Q,session 累積成本超過 cap,renderer 顯紅 banner
- `log` — debug log

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

## 主要功能(Phase 31 後狀態)

Phase 31-A~G 累積加上的功能:

### 對話管理
- **跨 app restart 持久化** — SQLite `~/.orion/sessions/cowork.db`,沒「關閉就丟」
- **Sidebar 分組** — Starred 區 + Recents 區,每筆 ⋯ 選單(Star / Rename / Move to project / Delete);Rename 走 inline edit
- **搜尋** — Title + 對話內容 + tool_result 全文(in-memory,單機規模 OK;FTS5 留 v2)
- **Compact 對話** — Auto-compact(threshold 可設)+ 手動 `/compact`;tombstone-based soft delete 保留 UI 歷史
- **Edit / Delete** — 對任何訊息點 ⋯ 編輯送回原 session,或刪除「該則之後」
- **Regenerate** — 重新生成最後一輪 assistant 回應
- **Fork**(Phase 31-R) — 任意訊息 hover toolbar 的 🌿「分叉」按鈕:從那則訊息(含)複製到新 session,原對話完全不動。新 session 繼承 workspace / project,budget / plan 不繼承;標 `forked_from_*` 系譜。常用情境:AI 給多方案各試一條、做有風險改動先 fork 保險、回到分歧點換問法

### 排程 / Loop(Phase 31-G)
共用同一張 `cowork_schedules` 表,差別在 `target_session_id`:

| 模式 | `target_session_id` | 觸發行為 |
|---|---|---|
| **Schedule** | NULL | 開**新對話 session** 跑 LLM(prompt 或 skill);每次獨立 |
| **Loop** | 既有 session_id | 送回**同對話** 接續(context 累積);跟既有 conversation 串連 |

兩者都跑 `SchedulerEngine`(asyncio 60s tick),app 開著就跑。
- LLM 對話設定:`ScheduleCreate` / `LoopCreate` builtin tool(host 注入 callback,SDK 不直接動 DB)
- UI 設定:Settings → 排程(`+ 新增排程` 含 cron preset + model picker + Act mode hint)
- 觸發出來的 session 在 Sidebar 顯時鐘 icon + scheduled_by badge

詳見 [`tools.md`](./tools.md) §Schedule。

### 專案
- **Project** = name + workspace_dir + custom_instructions;對話可選綁專案,專案 chat
  自動 cwd 到 workspace、注入 instructions、用 `<workspace>/.orion/{skills,memory,mcp.json,permissions.json,instructions.md}`
- **Co-located resources** — 專案 skills / memory / mcp 在 workspace 內,跟 git repo 一起 commit / share

### 技能系統
- 4 來源(bundled / system / project / user)last-wins
- `cowork_visible: false` frontmatter 讓 SDK skill 在 Cowork popover + Settings → 技能 隱藏(CLI 仍可用) — 用在 `batch`(worktree workflow)、`update-config`(改 `~/.orion/settings.json`,跟 Cowork GUI Settings 重疊)
- 詳見 [`skills.md`](./skills.md)

### 內建工具控制
- Settings → 工具 — 13 個 tool group(File / Shell / Search / Web / Skill / Schedule / Todo / Workdir / System / Task / Cron / Browser / Interactive),group 級 tri-state checkbox + 展開個別 tool override
- Disabled tools 存 `cowork_prefs.disabled_tools`(CSV),`build_default_tool_set` 過濾;變更立刻 invalidate conv cache

### Cost dashboard + budget cap(Phase 31-Q)
- **Per-session dashboard** — RightSidebar UsageSection 拉 `conversation.stats` 顯三層:本次 turn / session 累積 / context window;含 cache hit rate
- **Budget cap** — `cowork_session_ext.budget_usd_cap` 存 per-session 上限;turn 結束後 `_check_budget_and_notify` 算 cumulative cost,超過 → 設 `budget_exceeded` flag + emit `budget.exceeded` 通知,下次 `conversation.send` 在 pre-check 直接擋(error `BUDGET_EXCEEDED`)。調高 cap 自動 reset flag,可繼續送
- **Default budget** — Settings → Models 的 `BudgetPicker`(0 / $0.5 / $1 / $5 / $10 / 自訂),新 session 建立時帶入。Per-session 仍可在 RightSidebar BudgetSection 各別 inline edit
- **RPC**:`conversation.{get_budget,set_budget}`(讀 cap + current cost / 設或清 cap)

### 路徑統一(Phase 31-G)
Cowork 從獨立 root `~/.orion-cowork/` 搬進 `~/.orion/`,**skills / memory / mcp / users
跟 CLI / chat-api 共用**;sessions 透過 `sessions/cowork.db`(Cowork)vs `sessions/<uuid>/`
(CLI / chat-api)分開,兩 app 同跑不會 lock 衝突。詳見
[`../architecture/runtime-layout.md`](../architecture/runtime-layout.md) §2b。

### 桌面 OS 整合
- 圖檔附件:拖入 / paste / dialog 選檔三條 path,blob store(content hash)去重
- STT(Phase 31-D):麥克風錄音 → 上傳 OpenAI Whisper / GPT-4o transcribe
- TTS(Phase 31-T):每則 AI 回應 hover 有 🔊 念出按鈕。預設 Web Speech API(免費系統聲音);Settings 可切 OpenAI tts-1 / tts-1-hd × 6 voices × speed 0.5-2x。markdown / code 自動 strip;autoplay 開關「每則自動念」。全域單實例播放器,切下一則自動停舊的
- Browser use(Phase 31-F):AI 用 Playwright 控 system Chrome(headful)— `BrowserNavigate / Click / Type / Screenshot / ...`
- OS notifications:排程觸發完成 / 工具失敗等用 Web Notifications API

### Slash commands

| Command | 性質 |
|---|---|
| `/compact` | client — 觸發 manual compact |
| `/add-files` | client — 開檔案選擇器 |
| `/export` | client — bundle 全 sessions 成 ZIP 到工作資料夾 |
| `/context` | client — 顯 context window 用量分配卡 |
| `/schedule` | client — 跳 Settings → 排程 |
| `/loop` | LLM — `/loop 5m <prompt>`,LLM 走 bundled `loop` skill 解析參數呼 `LoopCreate` |
| `/goal` | LLM — `/goal <objective>`,LLM 走 bundled `goal` skill 條件驅動 self-iterate 達標自停 |
| `/agent` | LLM — `/agent <task>`,LLM 走 bundled `agent` skill 平行 spawn sub-agents(需 Settings → 工具 啟用 `Agent`)|
| `/<skill-name>` | LLM — 動態載入 bundled / user skill(popover 顯所有 `cowork_visible=true` 的) |

## 已 / 未實作

**已實作**(Phase 31-G 為止):
- ✅ Sidecar ~50+ RPC methods
- ✅ SQLite 持久化 + blob store + 圖檔附件
- ✅ MCP server 整合(global + per-project mcp.json)
- ✅ Multi-provider / model 切換 UI
- ✅ STT(OpenAI / Google)
- ✅ Browser use(system Chrome,headful)
- ✅ 排程 + Loop
- ✅ 工具 group 開關
- ✅ 完整 Electron + React UI(Sidebar / RightSidebar / Settings)
- ✅ Plan Mode wired(Phase 31-J)— `/plan` slash + 計畫審核 modal + read-only enforcement
- ✅ Per-session cost dashboard + budget cap(Phase 31-Q)— 超 cap 自停 + 通知
- ✅ 歷史對話 fork(Phase 31-R)— 任意 turn 分叉新 session,原對話不動
- ✅ E2e 測試(Playwright Electron)

**未實作 / Roadmap**:
- ❌ PyInstaller 單檔打包 + electron-builder cross-platform .app/.exe/.AppImage
- ❌ macOS notarization / Windows code signing
- ❌ Auto-update(electron-updater)
- ❌ OS-level 排程(app 關了仍跑)— 目前 app 必須開
- ❌ FTS5 全文搜尋(目前 in-memory)

詳見 [`../roadmap/`](../roadmap/)。

## 限制

- 大 tool result 走 stdio:目前無 cap,超大 payload 會塞滿 buffer。將來考慮:>1MB 走 disk + 傳 file path
- Windows 路徑 / line-ending:sidecar 寫 stdout 強制 `\n`(不 `\r\n`),main 端 split `\n`
- 多 in-flight requests:每個 request 帶 id,sidecar 開獨立 asyncio task,response 帶 id 路由給對應 handler
- 不重啟 sidecar:目前 sidecar 死掉只 reject 現有 requests,renderer 看到 error,需要 user manual reload。Production 該加自動重啟。

## 相關

- [`../architecture/packages.md`](../architecture/packages.md) §orion-cowork — 結構速覽
- [agent-loop.md](./agent-loop.md) — sidecar 內 SDK 怎麼跑
- [`../roadmap/`](../roadmap/) — 接下來要做什麼
