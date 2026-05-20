# Hooks

8 種 hook event,給 caller / plugin 注入「某事發生時跑點什麼」邏輯。

**實作位置**:`packages/orion-sdk/src/orion_sdk/hooks/`

## 8 event

| Event | 觸發時機 | 主要用途 |
|---|---|---|
| **SessionStart** | Conversation 建好 | 紀錄 session metadata、配置 logger |
| **SessionEnd** | shutdown / abort | flush metric、cleanup resource |
| **UserPromptSubmit** | User send 進來 | log、moderation、auto-translate |
| **PreToolUse** | Tool 跑前(permission decide 後) | audit log、metric、modify input |
| **PostToolUse** | Tool 跑完 | log result、trigger 後續 action |
| **Stop** | LLM 自然停 turn | metric、auto-summarize |
| **PreCompact** | Auto-compact 觸發前 | snapshot、selective preserve |
| **Notification** | 系統 notification 推出去前 | route 到 Slack / SMS / 等 |

## 註冊

```python
from orion_sdk.hooks import register_hook

async def log_pre_tool(event, ctx):
    print(f"Tool {event.tool_name} 即將跑,input={event.input!r}")

register_hook("PreToolUse", log_pre_tool)
```

Hook 函式可 async / sync,可 modify event(in-place)— 例如 PreToolUse 改 `event.input` 影響後續 tool 執行。

## Plugin 內掛 hook

```python
def plugin_entry() -> PluginEntry:
    return PluginEntry(
        ...
        hooks={
            "PreToolUse": [my_log_hook],
            "PostToolUse": [my_metric_hook],
        },
    )
```

## 設計取捨

- **Event 不可取消**:hook fail 不擋 main flow(swallow exception),避免 plugin bug 把 agent loop 弄死
- **Sync + async 都可**:hook function 由 SDK detect coroutine,sync 直接 call

## 限制 / 已知問題

- **沒 ordering**:多 plugin 註冊同 event,執行順序看 plugin load 順序(不確定)
- **沒 priority**:重要 hook 跟次要 hook 同等對待
- **沒 conditional skip**:hook 要 skip,只能函式內 early return

## 未來方向

- **Hook priority + ordering**:`@hook("PreToolUse", priority=10)`
- **Hook unregister**:test 場景 mock 後要能 clean
- **更多 event**:`OnError` / `OnTimeout` / `OnContextOverflow`

## 看完繼續

- [plugins.md](./plugins.md) — plugin 註 hook
- [agent-loop.md](./agent-loop.md) — hook 在 loop 哪幾段 trigger
