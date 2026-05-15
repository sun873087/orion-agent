# Recovery / Resume

中斷的對話可以從先前 session 繼續(reload 訊息歷史 + replacement state)。

**實作位置**:
- `packages/orion-sdk/src/orion_sdk/recovery/` — recovery 機制
- `packages/orion-sdk/src/orion_sdk/storage/resume.py` — 從 transcript 重建 Conversation

## Caller API

```python
from uuid import UUID
from orion_sdk.core.conversation import Conversation

conv = await Conversation.resume(
    session_id=UUID("..."),
    provider=llm,
    tools=tools,
)
# state_messages 自動從 ~/.orion/sessions/<id>/transcript.jsonl 重建
```

或 CLI:`orion run --resume <session-id> "繼續..."`

## Transcript 格式

每個 turn 一個 JSONL row,寫到 `~/.orion/sessions/<id>/transcript.jsonl`。內容含:

- user / assistant / tool messages(完整 NormalizedMessage)
- usage 統計
- tool result(>100KB 寫 sidecar 檔 + 留 placeholder,見 [compaction.md](./compaction.md))
- replacement_state(被 compact 替換掉的舊訊息的 metadata)

## Recovery 步驟

1. 讀 `transcript.jsonl` 全部 row
2. 解析每筆 → push 進 state_messages
3. 大 tool result 從 `tool-results/<id>.json` 還原
4. 重建 `replacement_state`(haven't compacted things)
5. caller 拿到 ready-to-go `Conversation`,call `send()` 就接著前面跑

## Crash recovery

`ConversationRecovery` 監聽 `Conversation.send()` 過程,異常時把進行中 state flush 到 disk。下次 `resume` 時可從 mid-turn 接回。詳見 `recovery/__init__.py`。

## 限制

- transcript 只有 append:對話越長 resume 越慢(線性 read)
- 大 transcript 沒有 streaming load(會吃 memory)
- 跨機器 resume 不可用:transcript 在 ~/.orion/,不是 portable URL
- Phase 7 Postgres mode 解這個:transcript 進 DB,跨機器可讀

## 相關

- [compaction.md](./compaction.md) — 被 compact 的 message 怎麼 resume
- [storage.md](./storage.md) — Session 持久化結構
