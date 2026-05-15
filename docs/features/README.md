# Features

各 feature 的**設計與運作**(非實作日誌)。每份回答「X 是什麼、怎麼運作、有什麼設計取捨」。

實作位置都標在文件開頭(`packages/orion-sdk/src/orion_sdk/X/` 等),想看 code 直接跳。

## 核心(agent loop 心臟)

| Feature | 一句話 | 主要模組 |
|---|---|---|
| [agent-loop.md](./agent-loop.md) | Conversation + QueryLoop + StreamingExecutor 怎麼跑 | `core/` |
| [tools.md](./tools.md) | 30+ 內建工具集 + 自訂 Tool 介面 | `tools/` |
| [streaming.md](./streaming.md) | LLM 事件流 → user-facing event 的轉換 | `core/`、`orion_model/events.py` |
| [permissions.md](./permissions.md) | Permission policy(always_allow / ask / DSL) | `permissions/` |

## 記憶與壓縮

| Feature | 一句話 | 主要模組 |
|---|---|---|
| [memory.md](./memory.md) | per-user / per-project 長期 memory + 四層防膨脹 | `memory/` |
| [compaction.md](./compaction.md) | 對話太長自動 / 反應式壓縮 | `compact/` |
| [prompt-caching.md](./prompt-caching.md) | Anthropic / OpenAI prompt cache 決策 | `prompt/`、`orion_model/cache_config.py` |
| [recovery.md](./recovery.md) | 中斷重啟、resume | `recovery/`、`storage/resume.py` |

## 擴充機制

| Feature | 一句話 | 主要模組 |
|---|---|---|
| [mcp.md](./mcp.md) | MCP server 整合(4 種 transport + OAuth) | `mcp/` |
| [skills.md](./skills.md) | Skill markdown bundles(動態載入 prompt) | `skills/` |
| [plugins.md](./plugins.md) | 第三方擴充 entry point | `plugins/` |
| [hooks.md](./hooks.md) | 8 種 hook event(SessionStart、PreToolUse、...) | `hooks/` |

## 多 agent

| Feature | 一句話 | 主要模組 |
|---|---|---|
| [multi-agent.md](./multi-agent.md) | Coordinator(leader-worker)+ Swarm(peer-to-peer) | `multi_agent/` |

## 環境與 I/O

| Feature | 一句話 | 主要模組 |
|---|---|---|
| [sandbox.md](./sandbox.md) | Docker / local 沙箱執行工具 | `sandbox/` |
| [storage.md](./storage.md) | Session 持久化 + 三層 budget + 大結果處理 | `storage/` |

## App 層

| Feature | 一句話 | 主要模組 |
|---|---|---|
| [chat-api.md](./chat-api.md) | FastAPI + WS + JWT server 行為 | `apps/orion-chat/api/` |
| [web-frontend.md](./web-frontend.md) | Vite + React 客戶端 | `apps/orion-chat/web/` |
| [cowork.md](./cowork.md) | Electron 桌機 app + Python sidecar | `apps/orion-cowork/` |

---

## 寫新 feature 文件

新增 feature 時順手在這寫一份,標題格式 `<name>.md`,結構建議:

1. **一句話定位** — 是什麼、解什麼問題
2. **實作位置** — 哪個 package、哪些模組
3. **API surface / 行為** — caller 看到什麼
4. **設計取捨** — 為何這樣不那樣(連結 `../architecture/design-decisions.md` 對應條目)
5. **限制 / 已知問題** — 老實寫,別蓋掉
