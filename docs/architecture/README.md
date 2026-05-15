# Architecture

orion-agent 是 multi-LLM agent harness — 用 anthropic + openai 兩個 SDK,**不**用第三方 agent framework。整個專案是 **uv workspace + npm workspaces 雙 monorepo**,拆成 2 個 package(reusable libs)跟 4 個 app(可獨立交付)。

## 結構速覽

```
orion-agent/
├── packages/
│   ├── orion-model/         純 LLM provider 抽象(Anthropic + OpenAI)
│   └── orion-sdk/           Agent runtime(Conversation loop + tools + ...)
│
└── apps/
    ├── orion-cli/           Terminal CLI(stdin / Typer)
    ├── orion-chat/
    │   ├── api/             FastAPI + WebSocket + JWT
    │   └── web/             Vite + React 客戶端
    └── orion-cowork/        Electron 桌機 app(透過 Python sidecar 用 SDK)
```

## 依賴流

```
                  orion-model    (純 LLM,無 agent loop)
                       ▲
                       │ depends on
                       │
                  orion-sdk      (agent runtime,依賴 orion-model)
                       ▲
        ┌──────────────┼──────────────┐
        │              │              │
   orion-cli      orion-chat-api  orion-cowork-sidecar
        │              ▲              ▲
                       │ HTTP/WS      │ stdio
                       │              │
                  orion-chat/web  orion-cowork/electron
                  (React)         (Electron main + React renderer)
```

**規則**(由 import-linter 強制):

1. `orion-model` 只 import 標準庫 + `anthropic` + `openai` + `httpx` + `pydantic` + `structlog`
2. `orion-sdk` 可 import `orion-model`,**不可** import `typer` / `fastapi` / `uvicorn`
3. App 層(cli / chat-api / sidecar)可 import sdk + model,**彼此不互相依賴**
4. `orion-chat/web` 跟 `orion-cowork/electron` 是 TS,不直接 import Python 程式,透過協定通訊

## 深入

| 想看... | 去 |
|---|---|
| 5 個 package 各做什麼、entrypoint 在哪 | [packages.md](./packages.md) |
| runtime 設定 / 資料散落哪幾個目錄 | [runtime-layout.md](./runtime-layout.md) |
| 重要設計取捨(為何不用 LangChain、為何 Cowork 不走 chat-api、...) | [design-decisions.md](./design-decisions.md) |

## 看完繼續

- 想知道某個 feature 怎麼運作 → [`../features/README.md`](../features/README.md)
- 想動手 → [`../guides/setup.md`](../guides/setup.md)
