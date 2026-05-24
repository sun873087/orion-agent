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

### Conversation 管理
- **多 session + tree view**:側邊欄 hierarchical(parent → fork children),按最近活動排序
- **Projects**:多 session 共享 workspace + system prompt
- **Session fork**:從任意 turn 開分支試另一條路;fork 在 user 訊息上自動 continue 觸發 AI 回應
- **Session title LLM 自然摘要**:仿 claude.ai 兩段式 — 跑完第一輪自動生中文短標題
- **背景多 session 並行**:切走的對話繼續跑,sidebar 顯示轉圈圈
- **Sidebar 批次刪除**:多選 toolbar,刪除 session 連同 fork 子孫一起刪
- **Plan mode**:LLM 唯讀調查 → 提計畫 → user 審核 → approve 後執行
- **/loop schedule**:cron-like 排程觸發 user-defined prompt;刪 session 時連帶清排程
- **Multi-pane collaboration**:tmux-like 多 pane 並排 + AskPane(pull) / DispatchPane(push)
  跨 pane 協作(詳見 [multi-pane-collaboration.md](./multi-pane-collaboration.md))

### 對話 UX
- **Follow-up 建議句 chip**:每 turn 完 LLM 猜下一句、Tab 採用
- **Empty state quick prompts**:4 個 chip 示範常用工具(空 session 引導)
- **訊息一鍵摘要**:長對話內單訊息點摘要按鈕
- **輸入框草稿保存 + 一鍵清空**:切 session 草稿留著,不丟資料
- **Tool approval banner 改人話**:Ask mode 下工具確認用自然語句,不是 RPC 名稱
- **Tool error「看不懂?讓 AI 解釋」**:tool error row 按鈕觸發 LLM 用人話翻譯紅字
- **訊息 👍👎 feedback**:單訊息打標,寫進 audit 給未來分析
- **? 鍵盤快捷鍵 cheat sheet**:全域 `?` 鍵叫出 modal 列所有 shortcut
- **@ mention popup**:`@file:path` 引用檔、`@skill:name` 載 skill、`@pane` collab 內跨 pane
- **Drag-drop 文字 / code 檔自動 inject**:檔 path 注入 prompt(混合 B+C 模式,不 inline 內容只給路徑)

### Audit / Privacy(A1+A2)
- **「為什麼這樣回答」per-turn audit**:每個 LLM turn 留 wire payload audit + dedup + 持久化
- **Wire payload audit modal**:點訊息看完整送 LLM 的 system / messages / tools(調 prompt 自己看)
- **隱私設定區**:Settings → Privacy 控制 audit 留多久 / 加密 / 是否寫
- **B2 跨對話搜尋**:Tool-only `conversation_search`,對齊 Anthropic 模式;支援 project / collab / session scope filter

### Cost / Budget
- **Per-session cost budget cap**:設 $cap,超 → 擋繼續 send,dashboard 顯月累計
- **Per-conversation cost icon**:Header 顯 `SessionCostBadge`,點開 RightSidebar 拆 breakdown
- **Cost ledger 全 LLM call 都算**:含 collab pane、title 生成、follow-up suggestion 全進 session 累積

### Voice
- **Voice input(STT)**:錄音 → 送 OpenAI Whisper 或 GPT-4o transcribe
- **TTS playback**:LLM 回應念出來,SHA256-hashed audio cache 避免重生

### Skills / Agents
- **Slash popover 動態列 skills**:`/<skill>` 觸發 + `cowork_visible` 開關隱藏 CLI-only 場景
- **`/agent` slash + bundled agent skill**:引導 LLM 用 sub-agent(AgentTool)
- **`/goal` skill + CLAUDE.md project guide**:project-level prompt 引入
- **`/plan` SDK Plan Mode 整合**:approval modal + 計畫檔走 `~/.orion/plans/`
- **AgentTool**:預設 disabled,user 自己 enable

### App-level
- **Soul.md**:Orion 對 user 的人格認識(個人化 system prompt 餘料)
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
