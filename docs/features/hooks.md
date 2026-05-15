# Hooks

8 種 hook event,給 caller 注入「在某事發生時跑點什麼」邏輯。

**實作位置**:`packages/orion-sdk/src/orion_sdk/hooks/`

## Event 列表

| Event | 觸發點 | 用途 |
|---|---|---|
| `SessionStart` | `Conversation.send` 第一次被叫(per conversation) | log session 啟動、注入 system prompt 動態段 |
| `UserPromptSubmit` | user message 被加入 state_messages 後 | filter / 改寫 user prompt |
| `PreToolUse` | tool 即將執行前 | permission check 替代、改 input、block 執行 |
| `PostToolUse` | tool 執行完(成功或失敗) | log、後處理、副作用 |
| `Notification` | 任意 user-facing 通知 | desktop notify、push、Slack |
| `Stop` | LLM `stop_reason="end_turn"` 但 caller 還沒中止 | 強制繼續、注入後續 prompt |
| `SubagentStop` | sub-agent(Agent tool / Task) 完成 | 收集 child 結果 |
| `PreCompact` | auto/reactive compact 觸發前 | 紀錄、stash 原始訊息 |

## 註冊

```python
from orion_sdk.hooks.registry import HookRegistry
from orion_sdk.hooks.events import PreToolUseEvent

hooks = HookRegistry()

@hooks.on("PreToolUse")
async def log_tool_use(event: PreToolUseEvent) -> None:
    print(f"about to run {event.tool_name}")

conv = Conversation(provider=llm, tools=tools, hooks=hooks)
```

## Hook 改變行為

某些 hook return 可以影響 flow:

- `PreToolUse` return `HookDecision.block` → 跳過該 tool
- `UserPromptSubmit` return 新字串 → 改寫 prompt
- 其他多半 read-only

## CLI / chat-api / cowork 各自的 hook 設定

- **CLI**:`~/.orion/settings.json` 內 `hooks: {...}` 設 shell command(`SettingsHook`)
- **chat-api**:webhook URL(POST event JSON 到外部 server)
- **Cowork**:目前無 hook UI(後續加)

詳見 [`../architecture/design-decisions.md`](../architecture/design-decisions.md) — Web chat 場景的 hook 設計差異。

## 限制

- Hook 跑在 agent loop 主進程,慢 hook 拖累 latency
- 沒有 hook timeout — 卡住會卡住 conversation
- Webhook 失敗預設 silent(可開 strict mode)

## 相關

- [skills.md](./skills.md) — 跟 hook 不同(skills 是注入 prompt,hooks 是注入邏輯)
- [plugins.md](./plugins.md) — 第三方擴充(用 hooks + tools)
