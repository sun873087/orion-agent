# Permissions

Tool 執行前的允許 / 拒絕決策。預設 `always_allow`(信任 LLM),production 場景可換 ask-user 或 DSL rule。

**實作位置**:`packages/orion-sdk/src/orion_sdk/permissions/`

## Policy types

### `always_allow`(預設)

```python
from orion_sdk.permissions.policies import always_allow
conv = Conversation(provider=llm, tools=tools, can_use_tool=always_allow)
```

CLI / dev / trusted 場景。

### `ask_via_callback`(互動)

```python
from orion_sdk.permissions.policies import ask_via_callback

async def my_asker(tool_name: str, tool_input: dict) -> bool:
    # CLI:input("Allow? y/n: ")
    # WS:ws.send(permission_ask) ... await ws.receive()
    return True

conv = Conversation(provider=llm, tools=tools, can_use_tool=ask_via_callback(my_asker))
```

### `DSL rule`(產線)

```python
from orion_sdk.permissions.dsl import compile_policy

policy = compile_policy([
    "allow Read(path=/home/me/projects/*)",
    "deny Bash(command=rm*)",
    "ask Bash",
])
conv = Conversation(provider=llm, tools=tools, can_use_tool=policy)
```

語法支援 glob、tool input field match、`allow` / `deny` / `ask`。

## CLI / chat-api / cowork 預設

| 環境 | 預設 policy |
|---|---|
| CLI(`orion run`) | `always_allow` |
| chat-api WebSocket | `ask_via_websocket`(透過 WS 跟 client 雙向) |
| Cowork sidecar(目前 Phase E) | `always_allow`(後續加 UI dialog) |

## 為何不放在 tool 本身

設計考量:permission 是 caller-side concern。同一個 `Bash` tool,CLI 信任 user,WS 要 ask front-end,production 要 deny destructive command。policy 跟 tool 解耦,改 policy 不動 tool code。

## 限制

- DSL rule 沒有 regex(只 glob)
- Ask 沒有 timeout — 卡住 conversation
- Policy 不能 stack(只接受一個 callable;要 stack 自己組合)

## 相關

- [tools.md](./tools.md) — Tool Protocol
- [chat-api.md](./chat-api.md) §Permission flow over WS — WS 端如何接 ask
