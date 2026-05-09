# Python FastAPI Port 計畫

把整個 Claude Code(TypeScript / Bun CLI)完整移植為 Python FastAPI 後端 + 對話介面。本資料夾每份文件對應一個實作階段(phase)。

> **背景**:本目錄下的 `docs/01-11` 是對 Claude Code 原始碼(`@anthropic-ai/claude-code@2.1.88`)的剖析。本 `phases/` 子目錄是依此剖析製作的 **Python port 執行手冊**。

## 整體目標

建構 `claude-agent-py`:一個用 Python 實作的 agent harness,功能對等 Claude Code 的核心(agent loop、工具、記憶、壓縮、權限、MCP),透過 FastAPI 提供給聊天前端使用。

## 11 階段 Roadmap

```
                        ┌──────────────────────────────────────┐
                        │  Phase 0:Foundation(2-3 週)         │ ← 起點
                        │  pyproject + Tool Protocol + 第 1 個工具│
                        └────────────────┬─────────────────────┘
                                         ▼
                        ┌──────────────────────────────────────┐
                        │  Phase 1:Agent Loop 核心(4-6 週)    │ ← 最大
                        │  Conversation + query_loop + 10 工具   │
                        └────────────────┬─────────────────────┘
                                         ▼
                ┌────────────────────────┼────────────────────────┐
                ▼                        ▼                        ▼
   ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
   │ Phase 2:Storage    │   │ Phase 3:Memory     │   │ Phase 4:Prompt      │
   │ State(3-4 週)      │   │ Compaction(3-4 週) │   │ Context(2-3 週)     │
   │ 三層持久化、resume   │   │ MEMORY.md、壓縮    │   │ system prompt 組裝  │
   └──────────┬──────────┘   └──────────┬──────────┘   └──────────┬──────────┘
              │                         │                         │
              └────────────────┬────────┴─────────────────────────┘
                               ▼
              ┌────────────────────────────────────┐
              │  Phase 5:MCP Integration(2-3 週)  │
              │  4 transport、動態 tool 包裝         │
              └────────────────┬───────────────────┘
                               ▼
              ┌────────────────────────────────────┐
              │  Phase 6:FastAPI Layer(2-3 週)    │
              │  WebSocket /chat/stream、前端 UI    │
              └────────────────┬───────────────────┘
                               ▼
              ┌────────────────────────────────────┐
              │  Phase 7:Sandbox + Production      │
              │  (3-4 週)                           │
              │  Docker per session、Postgres、S3   │
              └────────────────┬───────────────────┘
                               ▼
                ┌──────────────┴──────────────┐
                ▼                             ▼
   ┌─────────────────────────┐  ┌─────────────────────────┐
   │ Phase 8:Hooks/Skills/   │  │ Phase 9:Worktree+       │
   │ Plugins(3-4 週)         │  │ Telemetry(2-3 週)      │
   └─────────────────────────┘  └─────────────────────────┘
                │                             │
                └──────────────┬──────────────┘
                               ▼
                ┌────────────────────────────────────┐
                │  Phase 10:Tools + Performance      │
                │  (3-4 週)補完 30+ 工具 + 性能優化   │
                └────────────────────────────────────┘
```

## 各 Phase 一句話摘要

| Phase | 主題 | 時程 | 一句話摘要 |
|---|---|---|---|
| [00](./00-foundation.md) | Foundation + LLM Provider 雙支援 | 3-4 週 | 專案骨架 + Tool Protocol + AgentContext + LLMProvider 抽象(Anthropic + OpenAI 雙實作)+ 第一個工具,demo 可切換 Claude / GPT |
| [01](./01-agent-loop.md) | Agent Loop 核心 | 4-6 週 | Conversation + query_loop + StreamingExecutor + 10 個基礎工具 |
| [02](./02-storage-state.md) | Storage & State | 3-4 週 | 工具結果三層持久化 + transcript + resume 機制 |
| [03](./03-memory-compaction.md) | Memory & Compaction | 3-4 週 | MEMORY.md + Sonnet 動態挑選 + auto/reactive/snip 壓縮 |
| [04](./04-system-prompt.md) | System Prompt | 2-3 週 | 7 層堆疊 + section cache + DYNAMIC_BOUNDARY + cache scope |
| [05](./05-mcp-integration.md) | MCP Integration | 2-3 週 | 接 mcp Python SDK、4 種 transport、動態工具包裝 |
| [06](./06-fastapi-layer.md) | FastAPI Layer | 2-3 週 | WebSocket /chat/stream + 多 session + 前端 chat UI |
| [07](./07-sandbox-production.md) | Sandbox + Production | 3-4 週 | Docker per session、Postgres、Redis、S3、quota |
| [7c](./plan/7c-helm-chart.md) | **K8s 部署 + Helm chart**(📋 plan) | +1-2 週 | Pod-per-session、gVisor、NetworkPolicy、Helm(取代 07 的 Docker socket mount) |
| [08](./08-hooks-skills-plugins.md) | Hooks/Skills/Plugins | 3-4 週 | 8 種 hook event + skill frontmatter + plugin 市集 |
| [09](./09-worktree-telemetry.md) | Worktree + Telemetry | 2-3 週 | Sub-agent 隔離 + OpenTelemetry + cost tracker |
| [10](./10-tools-performance.md) | Tools + Performance | 3-4 週 | 補 30+ 工具 + async 優化 + cache 命中率調校 |
| [11](./11-input-pipeline.md) | **Input Pipeline(補)** | 1-2 週 | Slash 命令 + processUserInput + Image + Token estimation |
| [12](./12-internal-mechanics.md) | **Internal Mechanics(補)** | 1-2 週 | sideQuery + forkedAgent + Plan mode 狀態機 + AppState + file staleness |
| [13](./13-resilience.md) | **Resilience(補)** | 1-2 週 | Settings migrations + ConversationRecovery + Permission persistence + CLAUDE.md hierarchy |
| [14](./14-distribution-sync.md) | **Distribution & Sync(C 級補)** | 1-2 週 | settingsSync 跨機同步 + secureStorage(keychain / Vault) + DXT plugin format |
| [15](./15-multi-agent.md) | **Multi-Agent Patterns(C 級補)** | 1-2 週 | Coordinator(leader-worker)+ Swarm(peer-to-peer)+ AgentSummary |
| [Optional](./OPTIONAL.md) | **附錄** | — | IDE / Tips / MagicDocs / PromptSuggestion / Notifier 等可選特性 |
| [Web UI 規劃](./WEB_UI.md) | **測試 UI 規劃** | — | 三階段測試 UI(單檔 HTML → React 骨架 → 完整功能),含完整 Phase 0-1 的 50 行 test-ui.html 即用版 |

## ⚠️ Web Chat 場景已套用的調整

以下 phase 開頭都有「**Web Chat 場景調整**」區塊,對 SaaS / web chat agent API 場景的設計差異:

| Phase | TS CLI 設計 | Web Chat 改為 |
|---|---|---|
| **3 Memory** | per-project(`<git_root>/memory/`) | per-user(Postgres `user_memories` 表) |
| **5 MCP OAuth** | localhost callback port | server-side OAuth flow + secureStorage |
| **8 Hooks** | `settings.json` 寫 shell command | `webhook` URL(POST event JSON) |
| **8 Plugins** | git URL `git clone` 安裝 | curated registry + 簽名驗證 |
| **11 Input** | 103 個 slash 命令、`@file` ref、`!shell` | 精簡到 `/model` `/help` + 檔案上傳 + 拿掉 shell |
| **13 Custom Inst** | CLAUDE.md hierarchy(自動讀 `<cwd>/CLAUDE.md`) | per-user / per-conversation custom instructions(DB) |
| **14 Settings Sync** | client diff / merge / conflict | 直接 REST CRUD + 樂觀鎖 |

不變的核心(對 web chat 仍 100% 適用):Phase 0 / 1 / 2 / 4 / 6 / 7 / 7c(K8s plan)/ 9 / 10 / 12 / 15 / OPTIONAL。

**總計**:6-9 個月專注全職 / 12-24 個月業餘。

## 依賴關係

```
Phase 0 ◀─── 起點(沒依賴)
   │
   ▼
Phase 1 ◀─── 依賴 0
   │
   ├──▶ Phase 2(可獨立做)
   ├──▶ Phase 3(可獨立做)
   └──▶ Phase 4(可獨立做)
                │
                ▼
            Phase 5 ◀─── 依賴 1+4
                │
                ▼
            Phase 6 ◀─── 依賴 1(可省略 2-5,做最小聊天 demo)
                │
                ▼
            Phase 7 ◀─── 依賴 6
                │
                ▼
   ┌────────────┼────────────┐
   ▼            ▼            ▼
Phase 8     Phase 9      Phase 10
(可平行)    (可平行)      (可平行)
```

**可平行做的**:Phase 2 / 3 / 4 在 Phase 1 完成後可以三人分工同時做;最後三個(8/9/10)也是。

## 不做的事(精簡 scope)

從 Claude Code 原始碼**故意省略**的部分:

| 範疇 | 為何不做 |
|---|---|
| Ink UI / React reconciler | 換成 Web 前端,不需要 in-terminal React |
| Vim mode + keybindings | CLI 概念,前端有自己的快捷鍵 |
| Slash commands(`/clear` `/resume` 等)| FastAPI 用 REST/WebSocket 控制 session |
| Buddy(陪伴角色)| 純 UI 噱頭 |
| Voice(語音輸入)| 範疇外 |
| Bridge / Remote(CCR 整合)| 你自己就是 server,不需要橋接外部 server |
| KAIROS / PROACTIVE 模式 | Anthropic 內部實驗特性 |
| ant-only 工具(REPL、SuggestBackgroundPR、Tungsten)| Anthropic 內部 |
| Worktree 工具 | 用 Phase 7 的 Docker sandbox 替代 |
| 自製 file-index(nucleo fuzzy) | Python 直接用 `rapidfuzz` 或 `whoosh` |
| 自製 yoga-layout 綁定 | 沒有 Ink 就不需要 |
| 多版本 migrations(Sonnet 升級等)| 你自己控制版本,不需要從 Anthropic 模型版本遷移 |

## 對應 docs/01-11 的閱讀路徑

實作每個 phase 之前,先讀對應的 docs 章節掌握設計意圖:

| Phase | 必讀 docs | 補讀 docs |
|---|---|---|
| 00 | docs/01(架構總覽)、docs/11(工具目錄) | docs/02 |
| 01 | docs/02(agent loop)、docs/10(並發) | docs/06 模組 1-2 |
| 02 | docs/09(大結果) | docs/06 模組 7 |
| 03 | docs/07(記憶) | docs/06 模組 3-4 |
| 04 | docs/08(system prompt) | docs/05、docs/06 模組 5 |
| 05 | docs/04 §4c(MCP) | docs/06 模組 2、docs/10 §3(MCP 並發) |
| 06 | (無對應,新增 SaaS 層)| docs/04 整章 |
| 07 | (無對應,新增 SaaS 層)| docs/05、docs/09 |
| 08 | docs/05、docs/06 模組 9 | docs/01-02 |
| 09 | docs/06 模組 11 | docs/06 橫切關注點 |
| 10 | docs/11(剩餘工具)| docs/02 |

## 文件結構統一

每份 phase 文件都有 9 節:

1. **速覽** — 時程、依賴、交付物
2. **目標與動機** — 為什麼做、解決什麼
3. **TS 源檔映射** — Python 模組對應哪個 TS 檔
4. **任務拆解** — 可勾選清單
5. **模組架構與檔案** — 目錄樹
6. **Python Skeleton** — 關鍵 class/function 範例
7. **設計決策與取捨** — Python 化 vs TS 原版
8. **驗收標準** — 自動測試 + 手動驗證 + 整合
9. **常見踩雷** + **參考資料**

## 起手式

```bash
# 1. 讀完 docs/01-11 對 Claude Code 整體有概念
# 2. 讀 docs/phases/README.md(本檔)有 roadmap 概念
# 3. 讀 docs/phases/00-foundation.md 開始 Phase 0
# 4. 跑通 Phase 0 後繼續 Phase 1
# 5. 不要跳序(後面的 phase 都依賴前面)
```

## 心理建設

這是**馬拉松不是衝刺**。建議:

- **每 2 週設一個小 milestone**(不是每 phase),維持節奏感
- **每完成一個 phase 寫部落格 / 筆記**(學習目的最大回報)
- **測試從 day 1**(`pytest-asyncio` + `hypothesis`)
- **不追求 100% 對等**,Anthropic 自己都在迭代,訂目標是「能跑、能用、學到東西」
- **遇撞牆讀對應 docs/01-11 章節**,設計意圖通常在那裡
