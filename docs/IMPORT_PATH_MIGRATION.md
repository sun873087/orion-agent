# Phase 30:import path 改名對照表

Phase 30 monorepo 重構把 `api/src/orion_agent/` 一坨拆成 4 個 workspace package。
舊 docs / commit message / blog 內出現的 `orion_agent.*` 都依下表改名。

## 對照表

| 舊 path(Phase 0-29) | 新 path(Phase 30 後) | 所屬 package |
|---|---|---|
| `orion_agent.llm.*` | `orion_model.*` | `packages/orion-model` |
| `orion_agent.core.*` | `orion_sdk.core.*` | `packages/orion-sdk` |
| `orion_agent.tools.*` | `orion_sdk.tools.*` | `packages/orion-sdk` |
| `orion_agent.mcp.*` | `orion_sdk.mcp.*` | `packages/orion-sdk` |
| `orion_agent.sandbox.*` | `orion_sdk.sandbox.*` | `packages/orion-sdk` |
| `orion_agent.prompt.*` | `orion_sdk.prompt.*` | `packages/orion-sdk` |
| `orion_agent.memory.*` | `orion_sdk.memory.*` | `packages/orion-sdk` |
| `orion_agent.state.*` | `orion_sdk.state.*` | `packages/orion-sdk` |
| `orion_agent.storage.*` | `orion_sdk.storage.*` | `packages/orion-sdk` |
| `orion_agent.compact.*` | `orion_sdk.compact.*` | `packages/orion-sdk` |
| `orion_agent.recovery.*` | `orion_sdk.recovery.*` | `packages/orion-sdk` |
| `orion_agent.plan_mode.*` | `orion_sdk.plan_mode.*` | `packages/orion-sdk` |
| `orion_agent.multi_agent.*` | `orion_sdk.multi_agent.*` | `packages/orion-sdk` |
| `orion_agent.plugins.*` | `orion_sdk.plugins.*` | `packages/orion-sdk` |
| `orion_agent.skills.*` | `orion_sdk.skills.*` | `packages/orion-sdk` |
| `orion_agent.hooks.*` | `orion_sdk.hooks.*` | `packages/orion-sdk` |
| `orion_agent.output_styles.*` | `orion_sdk.output_styles.*` | `packages/orion-sdk` |
| `orion_agent.telemetry.*` | `orion_sdk.telemetry.*` | `packages/orion-sdk` |
| `orion_agent.perf.*` | `orion_sdk.perf.*` | `packages/orion-sdk` |
| `orion_agent.permissions.*` | `orion_sdk.permissions.*` | `packages/orion-sdk` |
| `orion_agent.services.*` | `orion_sdk.services.*` | `packages/orion-sdk` |
| `orion_agent.migrations.*` | `orion_sdk.migrations.*` | `packages/orion-sdk` |
| `orion_agent.api.*` | `orion_chat_api.*` | `apps/orion-chat/api` |
| `orion_agent.main` | `orion_cli.__main__` | `apps/orion-cli` |
| `orion_agent.commands.*` | `orion_cli.commands.*` | `apps/orion-cli` |
| `orion_agent.input.*` | `orion_cli.input.*` | `apps/orion-cli` |

## 故意未改名(OpenTelemetry 命名空間)

下列**不是** Python import path,而是 OTel span / metric 名稱,Phase 30 保留以維持
既有 dashboard / alert 相容性:

```
orion_agent.turn         (span name in telemetry/instrumentation.py)
orion_agent.tool         (span name)
orion_agent.turn.duration / orion_agent.tool.duration / orion_agent.tokens.* (metric names)
```

要改 OTel namespace 需另開 phase + 同步更新觀測平台。

## CLI / Server entrypoint 改名

| 舊 | 新 |
|---|---|
| `orion run "..."` | `orion run "..."`(不變) |
| `orion serve --port 8000` | `orion-chat-api serve --port 8000` |

## Docker image 跟 deploy

| 舊 | 新 |
|---|---|
| `docker build -f deploy/Dockerfile.api -t orion-agent-api:dev orion-agent/` | `docker build -f deploy/Dockerfile.api -t orion-chat-api:dev .`(repo root build context) |
| Container `WORKDIR /app/api`,`CMD uvicorn orion_agent.api.app:app` | `CMD ["orion-chat-api", "serve", "--host", "0.0.0.0", "--port", "8000"]` |

## 環境變數

不變(`ORION_DB_URL` / `ORION_DB_AUTO_CREATE` / `ORION_LOG_FORMAT` / `ORION_LOG_LEVEL` / `ORION_SANDBOX` / `ORION_JWT_SECRET` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 等都繼續用)。

## 舊 docs 怎麼處理

`docs/phase-0?-completion.md` 跟 `docs/phases/0?-*.md` 內 `orion_agent.X` 不主動改 —
歷史 commit 跟舊文件保留原 path 對 reader 反而是線索。需要時對照本表即可。
