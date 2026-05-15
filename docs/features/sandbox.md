# Sandbox

把 `Bash` / `Read` / `Write` / `Edit` 等動到 host 的工具關到隔離環境(Docker container 或受限 local subprocess),保護 host 不被 LLM 誤觸發。

**實作位置**:`packages/orion-sdk/src/orion_sdk/sandbox/`

## Backend 選項

| Backend | 用途 |
|---|---|
| `local` | 預設,工具直接動 host(無隔離)。dev / trusted 使用。 |
| `docker` | 每個 session 起一個 container,工具透過 docker exec 跑 |

CLI:`orion run --sandbox docker ...`
Chat API:`ORION_SANDBOX=docker` env var

## Docker backend 細節

- 每個 session 對應一個 `Container`(image 預設 `orion-agent-sandbox:dev`,見 `deploy/Dockerfile.sandbox`)
- 工具不直接執行,改 spawn `docker exec <container> <cmd>`
- 檔案 I/O:`Read`/`Write`/`Edit` 走 container 的 fs,host 看不到
- container 生命週期跟 session 綁:`SandboxBackend.cleanup()` 在 conversation 結束時刪除
- 啟動 cost ~500ms;session 第一次 tool call 才 lazy spawn

## 工具如何被 sandbox 攔截

`sandbox/proxy_tools.py`:`build_sandboxed_tools(backend)` 回 wrap 過的 tool list。每個 tool 的 `run()` 改成把 input 序列化 → 透過 backend 跑 → 解析 output。

`Conversation` caller 決定要不要傳 sandboxed tools:

```python
from orion_sdk.sandbox.factory import get_sandbox_backend
from orion_sdk.sandbox.proxy_tools import build_sandboxed_tools

backend = get_sandbox_backend("docker")
tools = build_sandboxed_tools(backend)
conv = Conversation(provider=llm, tools=tools, sandbox_backend=backend)
```

## K8s production(未實作)

Phase 7 docker socket mount 只適合本機 dev。Production 用 K8s pod-per-session + gVisor + NetworkPolicy。完整設計見 [`../roadmap/plans/7c-helm-chart.md`](../roadmap/plans/7c-helm-chart.md)。

## 限制

- Docker daemon 必須 reachable(本機 unix socket 或遠端 daemon)
- container image 預先 build:`docker build -f deploy/Dockerfile.sandbox -t orion-agent-sandbox:dev .`
- 跨 OS 路徑問題(host `/Users/yuan-sencheng/foo` ↔ container `/work/foo`)由 backend 內部 mount mapping 處理
- session abort 時 container 不立即殺,等 `cleanup()` 被叫到才走

## 相關

- [tools.md](./tools.md) — Tool Protocol
- [agent-loop.md](./agent-loop.md) — `sandbox_backend` 透過 `AgentContext` 傳到 tools
