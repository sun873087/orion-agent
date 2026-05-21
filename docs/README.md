# Orion Agent

模組化、多 LLM 的 agent runtime。可以用 CLI 跑、可以開 web 跑、可以包 Electron 桌機跑;
也可以把 OpenAI / Anthropic 的所有 API 通通走自家 proxy 集中計費 / 限速。

## 一句話定位

> **orion-agent** = SDK + 三個 app + 一個 proxy。
> 寫 prompt 餵 LLM 拿結果不稀奇 — 把「對話 / 工具 / 權限 / 記憶 / 計費 / 多人」
> 統整成一個跑得起來的 runtime,才是這專案的 value proposition。

## 哪幾塊?

```
orion-agent/
├── packages/
│   ├── orion-model        ← 純 LLM provider 抽象(Anthropic / OpenAI / Ollama)
│   ├── orion-sdk          ← Agent runtime:對話 loop、工具、權限、記憶、MCP、...
│   └── orion-model-proxy  ← Optional HTTP 服務,集中 API key / cost / routing
└── apps/
    ├── orion-cli          ← 終端機 chat,各 tenant 各自 sessions/
    ├── orion-chat         ← FastAPI server + React web client
    └── orion-cowork       ← Electron 桌機 app(透過 Python sidecar 用 SDK)
```

3 個 app 都 `import orion_sdk` 跑同一份 agent loop。差別只在 session 怎麼存
跟 host 整合面。

## 文件結構

| 區 | 目的 | 何時讀 |
|---|---|---|
| **[architecture/](./architecture/)** | 結構、package 拆分、依賴規則、設計取捨 | 想知道「東西長什麼樣 / 為何這樣」 |
| **[features/](./features/)** | 各 feature 設計與行為(agent loop / tools / memory / MCP / model-proxy / ...) | 想知道「X 怎麼運作」 |
| **[guides/](./guides/)** | 操作手冊(setup / tests / build / 排錯) | 想動手做某件事 |
| **[roadmap/](./roadmap/)** | 未來發展方向 | 想看「之後會走哪」 |

## 新人路徑

1. 5 分鐘掃 [`architecture/README.md`](./architecture/README.md) — 拓樸 mermaid 圖一覽
2. 15 分鐘照 [`guides/setup.md`](./guides/setup.md) — 跑通本機(`make install` + `make test`)
3. 挑感興趣的 feature 跳 [`features/`](./features/) 進去讀
4. [`roadmap/README.md`](./roadmap/README.md) 看下一步方向

## Quick links

| 我要... | 去 |
|---|---|
| 第一次安裝 / 跑通本機 | [`guides/setup.md`](./guides/setup.md) |
| 跑測試 | [`guides/run-tests.md`](./guides/run-tests.md) |
| 看 6 個 package 各做什麼 | [`architecture/packages.md`](./architecture/packages.md) |
| 看 runtime 資料 / 設定在哪個目錄 | [`architecture/runtime-layout.md`](./architecture/runtime-layout.md) |
| 看 agent loop 怎麼跑 | [`features/agent-loop.md`](./features/agent-loop.md) |
| 看內建工具集 | [`features/tools.md`](./features/tools.md) |
| 看 model proxy(計費 / 限速 / multi-tenant) | [`features/model-proxy.md`](./features/model-proxy.md) |
| 看 memory 系統 | [`features/memory.md`](./features/memory.md) |
| 看為何 Cowork 不走 chat-api | [`architecture/design-decisions.md`](./architecture/design-decisions.md) |
| 看企業規模 / 跨國場景設計筆記 | [`roadmap/enterprise-scale.md`](./roadmap/enterprise-scale.md) |
| 看 multi-pane 多 agent 協作(實作版) | [`features/multi-pane-collaboration.md`](./features/multi-pane-collaboration.md) |
| 看 multi-pane 設計筆記 / 未來方向 | [`roadmap/multi-pane-collaboration.md`](./roadmap/multi-pane-collaboration.md) |
| 看 multi-mode collab(Coordinator/Swarm 接 GUI) | [`roadmap/multi-mode-collab.md`](./roadmap/multi-mode-collab.md) |
| 卡關 | [`guides/troubleshooting.md`](./guides/troubleshooting.md) |

## 寫文件原則

新增文件先判斷它屬於哪一區:

- **architecture/** — 描述「東西怎麼長」(static structure)
- **features/** — 描述「某個 feature 怎麼運作」(behavior)
- **guides/** — 描述「如何做某件事」(action)
- **roadmap/** — 描述「打算做某件事 / 朝哪個方向」(intent)

混了兩件事就拆兩份。

### 其他規則

- **不寫 Phase 編號**(完工事實看 git log,文件描述「現況」)
- 不寫實作日誌、不寫「我們」、「剛剛」、「最近」這類相對時間
- Reference 性質的事實(套件名、env var、檔路徑)隨 code 同步更新
- 過期文件直接刪,不留 "deprecated" 標籤拖
