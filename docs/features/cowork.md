# Cowork

PC 本地桌機 app。**不**連 chat-api,Electron main process spawn 一個 Python sidecar 直接
`import orion_sdk` 跑 agent loop。

**實作位置**:`apps/orion-cowork/`

## 為何不走 chat-api

- 本機單機不需要 HTTP / JWT / CORS
- stdio 比 socket 安全(沒 port 暴露)
- JSON-RPC streaming 比 REST 適合 notification 隨時推
- 延遲低、UI 流暢

要把 Cowork 改 SaaS 直接接 chat-api,sidecar 直接刪 — 設計上保留這條 path。

## 架構

```
Electron main process(main.ts)
    │
    ├─ BrowserWindow(React renderer)
    │       │
    │       └─ contextBridge → window.{agent, dialog, scheduler, plan, budget,
    │                                  backup, updater, shell, ...}Api
    │
    └─ Spawn Python sidecar(sidecar.ts)
            │ stdin / stdout JSON-RPC
            ▼
        sidecar handlers.py
            │
            ▼
        orion_sdk.Conversation(...)
```

3 個 process(main + renderer + sidecar)各自獨立,IPC 串起。

## Sidecar(Python)

```
sidecar/src/orion_cowork_sidecar/
├── __main__.py             uv run entrypoint + ORION_CLIENT_ID setdefault
├── rpc.py                  stdio JSON-RPC server(append `id` + final flag)
├── handlers.py             所有 RPC method(2000+ 行)
├── storage.py              SQLite engine(`~/.orion/sessions/cowork.db`)
├── scheduler.py            /loop schedule + cron (apscheduler)
├── backup_handlers.py      整個 ~/.orion/ zip 備份 / restore
├── stt_handlers.py / tts_handlers.py
├── mcp_integration.py      Cowork-side MCP wiring + RPC
└── desktop_tools.py        OpenPath / OpenUrl (本機 desktop 專屬)
```

跑法:`uv run --package orion-cowork-sidecar orion-cowork-sidecar`(由 main process spawn,user 不直接跑)。

## Renderer(React)

```
renderer/src/
├── App.tsx                 Layout + global state init + notification listeners
├── components/
│   ├── Sidebar.tsx         Session tree + Project switcher
│   ├── Header.tsx          Workspace badge + model selector + SessionCostBadge
│   ├── InputBox.tsx        Prompt input + slash + ErrorBanner + voice button
│   ├── MessageList.tsx     Messages + tool cards + auto-compact banner
│   ├── RightSidebar.tsx    Per-session usage / budget / context window stats
│   ├── SettingsPage.tsx    9 個 tab(General / Models / Memory / Skills / Tools / Schedules / MCP / Permissions / Backup / About)
│   ├── ProjectSettingsPage.tsx
│   ├── PlanApprovalModal.tsx
│   └── ...
├── store/                  Zustand(agent / settings / projects / sessionTree)
├── api/                    JSON-RPC wrappers(window.agent.call 包裝)
├── hooks/                  useSendPrompt / useProjects / ...
└── i18n/                   4 locale(zh-TW / zh-CN / en / ja)
```

## 主要 features

- **多 session + tree view**:側邊欄 hierarchical(parent → fork children)
- **Projects**:多 session 共享 workspace + system prompt
- **Voice input(STT)**:錄音 → 送 OpenAI Whisper 或 GPT-4o transcribe
- **TTS playback**:LLM 回應念出來,SHA256-hashed audio cache 避免重生
- **/loop schedule**:cron-like 排程觸發 user-defined prompt
- **Plan mode**:LLM 唯讀調查 → 提計畫 → user 審核 → approve 後執行
- **Session fork**:從任意 turn 開分支試另一條路
- **Per-session budget cap**:設 $cap,超 → 擋繼續 send
- **Per-conversation cost icon**:Header 顯 SessionCostBadge,點開 RightSidebar
- **Backup / Restore**:`~/.orion/` 全 zip → 桌機機交換 + 重灌復原
- **Auto-update**(electron-updater):GitHub Releases → 自動下載 → user 按 restart
- **OS notification**:LLM done / scheduler fired 推到桌機 notification center

## Data layout

`~/.orion/sessions/cowork.db`(SQLite):

- SDK 共用表:`sessions` / `messages`
- Cowork 擴充:`cowork_session_ext` / `cowork_projects` / `cowork_schedules` /
  `cowork_plan_state` / ...

跨 host 共用 `~/.orion/{skills,users/<u>/memory,mcp.json,blobs,plans}/`。

## Packaging

`electron-builder.yml`:
- macOS:DMG(arm64 + x64),hardenedRuntime + entitlements(notarize env-gated)
- Windows:NSIS exe(env-gated signing)
- Linux:AppImage
- Auto-update via `publish: github`(GitHub Releases)

Build flow:
```
build:sidecar      → PyInstaller 把 Python sidecar 打 single binary
build:renderer     → Vite build static assets
build:electron     → tsc 編 main / preload / updater / sidecar.ts
dist               → electron-builder pack 全部成 DMG/exe/AppImage
```

## 設計取捨

- **stdio JSON-RPC 不 HTTP**:本機單機,REST overkill
- **Sidecar 用 Python 而非 Node**:agent runtime 寫在 Python(orion-sdk),sidecar 直接 import
- **SQLite 不 Postgres**:本機 1-user,SQLite 對 30+ session 切換最快
- **Skills / Memory / MCP 跨 host 共用 `~/.orion/`**:user 在 CLI 加的 memory,Cowork 看得到

## 限制 / 已知問題

- **macOS unsigned build 要右鍵 → 開啟**:Gatekeeper 擋 → 第一次手動 bypass
- **Sidecar process crash → renderer 卡 spinner**:main 沒 watchdog
- **大 attachment 走 base64 經 stdio**:幾 MB 圖會塞慢 stdio buffer
- **No live collaboration**:Cowork 本機單 user(team / multi-user 是 chat-api 的事)

## 未來方向

- **Sidecar watchdog**:crash 自動 restart + renderer reconnect
- **Multi-window**:同 app N 個 window 看不同 conversation
- **Headless mode**:CLI 啟動 sidecar 後不開 UI,給 automation 用
- **macOS code signing CI**:GitHub Actions 自動跑 notarize
- **Voice realtime**:OpenAI Realtime API(WS)— 直接 voice → voice
- **iPad / mobile companion app**:看 conversation 即時 push(不能 send,只能 monitor)

## 看完繼續

- [`../architecture/packages.md`](../architecture/packages.md) — Cowork 三部分(electron / renderer / sidecar)
- [`../architecture/runtime-layout.md`](../architecture/runtime-layout.md) — Cowork 用哪些目錄
- [chat-api.md](./chat-api.md) — Web frontend 對比
