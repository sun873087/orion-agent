# Permissions

Tool 執行前的允許 / 拒絕決策。預設 `always_allow`(信任 LLM),production 場景可換 ask-user 或 DSL rule。

**實作位置**:`packages/orion-sdk/src/orion_sdk/permissions/`

## 3 種 mode

| Mode | 行為 |
|---|---|
| **always_allow** | 全放行 — dev / single-user 信任 LLM 的場景 |
| **ask** | 每次 tool call 問 user(via `tool_approval_request` event)— Cowork 預設 |
| **dsl** | YAML / JSON 規則(per tool + path glob + arg pattern)— enterprise |

## Mode 切換

Per-session 在 ctx 設:

```python
from orion_sdk.permissions.policy import (
    AlwaysAllowPolicy, AskPolicy, DslPolicy,
)

ctx.permission_policy = AlwaysAllowPolicy()
# or AskPolicy(asker=cowork_ask_callback)
# or DslPolicy(rules_file="~/.orion/permissions.json")
```

## DSL 範例

```yaml
- tool: Bash
  match: { command: "^rm -rf" }
  decision: deny
  reason: "Bulk delete blocked by policy"
- tool: Write
  match: { file_path: "^/etc/" }
  decision: deny
- tool: WebFetch
  match: { url: "internal.company.com" }
  decision: allow
- default: ask
```

## 介入時機

`StreamingExecutor.execute()` 內,每個 tool_call 跑前 call `policy.decide(tool_name, input, ctx)`:
- `allow` — 直接跑
- `deny` — emit ToolResult(is_error=True, text="permission denied: ...")
- `ask` — emit ToolApprovalRequest event,host 收後彈 UI;reply 寫回 ctx future

## Plan mode 自動 wrap

`enter_plan_mode()` 後,SDK 自動把所有非唯讀 tool 改 deny(只 Read/Grep/Glob/WebFetch/
AskUserQuestion 等放行)。host 不必動 policy。

## 限制 / 已知問題

- **DSL 語法還沒完整定**:目前只 path glob + simple match,沒 condition expression(AND/OR/NOT)
- **跨 session policy reload**:改 `permissions.json` 要重啟 host
- **Sub-agent permission 繼承**:`AgentTool` spawn 子 agent 時 policy 是繼承還是 reset 沒明確設計

## 未來方向

- **DSL 完整**:rego-like / OPA-light expression
- **Per-MCP-server policy**:某些 MCP server 整批不信任(allowlist 才放行)
- **Audit trail**:每筆 decision 留 log(目前只 deny 時 emit event)

## 看完繼續

- [agent-loop.md](./agent-loop.md) — Permission 在 loop 哪一段介入
- [tools.md](./tools.md) — 各 tool 的 input shape(寫 DSL 時要對)
