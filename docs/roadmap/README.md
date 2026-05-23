# Roadmap

orion-agent 的 vision + 未來方向。**主題式組織**(不按 phase 編號)— 每個主題各自演進
速度可能不同,不互相 block。

## Vision

> 把「跟 LLM 對話」昇華成「持續可用的 agent runtime」。
> User 該關心的是 prompt + workspace,不是「token 怎麼算 / cache 哪一段 / tool 怎麼接」。

具體目標:

1. **單機到 SaaS 同套**:從 CLI single-user 到 team SaaS,**同一份 SDK**,不重寫
2. **可治理的成本**:每 user / org 都有 cap + audit trail + 預警 — admin 不必猜
3. **可擴充不過度設計**:Skills(markdown)+ Plugins(Python entry point)+ MCP(外部 server)三層,各自場景
4. **跨平台、跨 model**:Anthropic / OpenAI / Ollama 同套 API,model 可換、provider 可換、deployment 可換

## 領域

### 🎯 Cost & governance

**現況**:Model proxy 提供 multi-tenant + per-user budget + audit log + webhook + admin UI。
但都還是「單 proxy instance」場景。

**方向**:

- **Multi-org**:已有 `organizations` 表,但 per-org budget rollup / org admin role 未做
- **Cost prediction**:LLM call 前 estimate token / cost,user 可預知大筆消費
- **Bill 報表**:月度 PDF / CSV export 給財務
- **Soft budget warning**:80% / 90% threshold(現只 80%/100%)+ Slack / email 推
- **Multi-proxy HA**:Redis-backed rate limit cache + Postgres shared DB
- **Audit retention policy**:>1 年 audit log 壓進 cold storage / S3

### 🛠 Developer experience

**現況**:CLI / Cowork / chat-api 都跑得起來,測試 1100+ 綠。Onboarding 從 30 分→ `make proxy-bootstrap` 一鍵 3 分。

**方向**:

- **First-run wizard**(Cowork):新 user 啟動 → guided 設 API key / model / workspace
- **One-click MCP installs**:Settings 內瀏覽 MCP server marketplace,點安裝
- **Skill / Plugin marketplace**:user-contributed 倉庫,標安全評分
- **Better error UX**:目前 ErrorBanner 可展開 / 複製 / 關閉,但 error → 動作 hint 還可深(e.g. 401 → "Run `make proxy-bootstrap`")
- **Hot-reload skills / catalog**:不必重啟 host
- **`orion doctor` CLI**:診斷常見問題(env 缺漏 / DB schema mismatch / sandbox 沒裝)

### 🤖 Model & wire

**現況**:Anthropic + OpenAI + Ollama,SSE streaming,proxy 透傳。

**方向**:

- **更多 provider**:Cohere、Mistral、Groq、Google Gemini、xAI Grok、自架 vLLM(走 OpenAI-compat)
- **WebSocket Realtime**:OpenAI Realtime API + Anthropic 之後類似 API。proxy `/openai/v1/realtime` skeleton 已建,需實作 WS reverse proxy
- **Embedding model abstraction**:目前 embedding 直連 OpenAI,要 provider-neutral
- **Cross-provider failover**:`failover.py` 骨架已建,需跨 provider wire 互轉(model 名 mapping + system prompt 翻譯)
- **Smart routing**:user 設「想要 reasoning model」→ proxy 自動 pick gpt-5 / claude-opus-4-7 / o3 中可用 + 最便宜的

### 🧠 Memory & knowledge

**現況**:per-user / per-project markdown memory,bag-of-words ranker + LLM ranker 可選。

**方向**:

- **Vector embedding ranker**:semantic similarity,跨語言友善
- **Auto de-duplication**:新 memory 寫入時 fuzzy match 既有,合併而非新增
- **Knowledge base import**:從 markdown / notion / confluence 一鍵 import 變 reference memory
- **Memory edit history**:每次 LLM 改 memory 留 diff,看演化
- **Cross-user shared memory**(team):reference memory 可標 team-wide,所有 member 看
- **Project workspace indexing**:對話開始時掃 workspace 主要 file → 自動 inject 概要

### 🔌 Extension points

**現況**:Skills(markdown)+ Plugins(Python entry point)+ MCP(4 種 transport)。

**方向**:

- **Plugin marketplace**:`pip install orion-plugin-*` discovery + 安裝預覽
- **Plugin sandbox**:WASM / subprocess 隔離(目前 plugin 是 Python code,可做任何事)
- **Plugin capability declaration**:plugin 宣告需要哪些權限,user 同意才載入
- **MCP server marketplace + 一鍵安裝**(Cowork Settings)
- **MCP supervisor resume**:server crash 自動 restart + state recovery
- **Tool versioning**:cross-version transcript replay 不撞 schema mismatch

### 🤝 Multi-agent

**現況**:Coordinator(leader-worker)+ Swarm(peer-to-peer)早期,sub-agent spawn OK。

**方向**:

- **Cost attribution**:sub-agent 跑的 token 算 parent session(`usage_log.parent_session_id`)
- **Persistent agent identity**:agent 有 long-lived identity,可跨 session 復用
- **Swarm 訊息持久化**:peer message queue 進 DB,crash recovery
- **Resource limits**:per-agent CPU / memory / token budget(避免 swarm 爆預算)
- **Role library**:預設角色(researcher / code-reviewer / planner)— user 拼裝

### 🖼 Cowork(desktop UX)

**現況**:Electron + sidecar 全功能,backup / restore + auto-update + per-session cost icon。

**方向**:

- **macOS code signing CI**:自動 notarize + 發布 GitHub Release
- **Multi-window**:同 app N 個 window 看不同 conversation
- **Headless mode**:CLI 啟動 sidecar 但不開 UI,給 automation
- **Voice realtime UI**:OpenAI Realtime → 直接 voice in / voice out
- **iPad / mobile companion**:看 conversation 即時 push(不送,只 monitor)
- **Live collaboration**:多 user 同 session(co-edit chat)
- **Workspace file inline preview**:`@<file>` reference 滑鼠移上 hover preview
- **Sidecar watchdog**:crash 自動 restart + renderer reconnect

### 🌐 Web frontend(chat-api)

**現況**:Vite + React 客戶端 + JWT auth + OAuth providers(GitHub / Linear / Google / Microsoft)。

**方向**:

- **Virtual scrolling**:對話 1000+ messages 不 lag
- **Offline draft + PWA**:wifi 斷網 / 行動裝置加進主畫面
- **i18n**:加 zh / ja(目前只 en)
- **Org / team UI**:給 admin 看自家 user 用量 + budget
- **Push notification(FCM / APNS)**:行動端通知

### 📊 Observability

**現況**:OTel skeleton(env-gated lazy import),proxy 跑 spans。Audit log 全 admin 操作。

**方向**:

- **OTel 拉滿**:proxy / sidecar / SDK 系統性 emit spans(目前 proxy `_track_usage` 有)
- **Metric exporter**:Prometheus `/metrics` endpoint(request count / latency / cache hit / ...)
- **Grafana dashboard**:預建 dashboard JSON,user 一鍵 import
- **Structured JSON logs**:跨 host 收 ELK / Datadog
- **Trace correlation**:`X-Orion-Request-Id` 串 client → proxy → upstream → log

### 🔒 Security & compliance

**現況**:Permission policy(always_allow / ask / DSL)+ sandbox(none / local / docker)+ token rotation。

**方向**:

- **Audit retention + 不可竄改**:append-only audit log(SQLite WAL OK,但要更 robust)
- **Encrypted blob store**:`~/.orion/blobs/` 對個人資料加密(目前明文)
- **SSO**:SAML / OIDC 替 username/password
- **2FA / MFA**:admin token 加 TOTP
- **GDPR data export**:user 一鍵 export 全部 data + delete

### 🏗 Infrastructure

**現況**:單機 / 單實例 / SQLite 為主。

**方向**:

- **Postgres production-ready**:proxy + chat-api 都已支援,但 connection pool / index / migration 還沒打磨
- **Redis-backed cache**:rate limit / running cost / prompt cache 共享給多 instance
- **K8s helm chart**:proxy + chat-api 一鍵部署
- **Multi-region**:proxy / chat-api 跨 region(誰負責 user 的 session?)
- **Backup-restore 跨 backend**:SQLite → Postgres / 反向(目前同 backend OK,跨 backend 需 schema convert)

## 企業規模 / 跨國場景

公司內部 1 萬人 + 跨國 = 完全不同 league(SSO / region-pinned 資料 / DLP /
audit / SCIM / MDM / cost-center 計費 / 多 LLM provider failover ...)。
**目前不在實作範圍**,但設計思考已留檔給未來。

→ [`enterprise-scale.md`](./enterprise-scale.md)

## Multi-pane collaboration(tmux-like 多 agent 工作台)

把 Cowork 升級成「一 window 同時跑 2-4 個 agent,各自 model / persona,可
cross-pane reference」。受 tmux 啟發,目標是讓「多 agent 協作」**互動式可見**,
而非 SDK 既有 Coordinator/Swarm 的 headless 場景。**目前不在實作範圍**,設計
細節(對話記錄 / cross-pane skill / workspace 衝突 / UI / 成本)留檔。

→ [`multi-pane-collaboration.md`](./multi-pane-collaboration.md)

## Conversational UX polish — 給非工程使用者也用得順

Cowork 的對話體驗仍偏「工程使用者懂的工具」(banner 顯 `Glob *`、session
title 寫整段原 prompt、tool error 是 stack trace)。沿用 cheap LLM small model
channel(`compact_summary_provider`),accumulate 一系列「看不懂才付費」的優化:
title 自動摘要、banner 翻譯、tool 解釋、tool error 解釋、follow-up 建議句、
訊息一鍵摘要、輸入框草稿保存、cost ledger + breakdown UI(所有 cheap LLM call
都算進累積,UI 拆 7 個 origin 顯給 user)、soul.md(Orion 對你的人格認識,
取自 [soul.md](https://soul.md/) 概念)、`?` 快捷鍵 cheat sheet 已完成,接下來
想做 vague prompt 補問、訊息「再答一次」、Cmd+K command bar 等。
**設計原則**:0 預設成本、LLM 失敗 silent fallback、prompt injection 防護、
沿用單一 cheap model channel。

→ [`conversational-ux-polish.md`](./conversational-ux-polish.md)

## Multi-mode collab(Coordinator / Swarm 接 GUI)

接著 multi-pane,把 SDK 既有的 Coordinator(leader fan-out workers)/ Swarm
(peers 互傳訊息)兩種 headless pattern 也接進 Cowork GUI。NewCollaborationModal
加 mode picker,user 選「並排 pane / 平行加速 / 自由辯論」。Coordinator 的
visibility win 最強(看得到每個 worker stream),Swarm 標實驗性。**未做**,
設計筆記留檔,等真實需求出現再啟動。

→ [`multi-mode-collab.md`](./multi-mode-collab.md)

## 不會做的(明確 out-of-scope)

- **自家 LLM training**:orion 是 client-side agent runtime,不訓 model
- **GUI workflow editor**:visual node-based flow(像 n8n / langflow)— orion 走 prompt-driven 不 UI-flow
- **Web search engine 自家做**:用 SerpAPI / Tavily / 等
- **Image generation 自家做**:用 OpenAI Images API / Replicate / 等
- **Mobile native app(完整)**:companion app 看 conversation 可以,但完整 mobile chat 太大坑

## 看完繼續

- [`../README.md`](../README.md) — 整體入口
- [`enterprise-scale.md`](./enterprise-scale.md) — 企業規模 / 跨國的設計筆記(未來再啟動)
- [`multi-pane-collaboration.md`](./multi-pane-collaboration.md) — tmux-like 多 agent 工作台設計
- [`multi-mode-collab.md`](./multi-mode-collab.md) — Coordinator / Swarm 接 GUI 的設計與切片
- [`conversational-ux-polish.md`](./conversational-ux-polish.md) — 對話 UX 給非工程使用者的優化清單
- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) — 已決定的事
- [`../features/`](../features/) — 各 feature 的「未來方向」段落(各篇 inline)
