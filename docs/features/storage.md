# Storage

對話 / 大結果 / 使用者資料的持久化。三層 budget(避免單 turn 訊息爆掉 context)。

**實作位置**:`packages/orion-sdk/src/orion_sdk/storage/`

## 三層儲存

```
~/.orion/sessions/<session-id>/
├── transcript.jsonl       # 對話 history(append-only)
├── meta.json              # 可選 metadata
├── tool-results/          # 大 tool result(>= 100KB)
│   └── <tool-use-id>.json
├── file-history/          # Edit/Write 寫前快照(LRU 100,Phase 19)
└── replacement_state.json # compact 替換決策歷史
```

## Backend

| Backend | 設定 | 用途 |
|---|---|---|
| **In-memory** | 預設 | dev / 單機,程序退就丟 |
| **SQLite** | `ORION_DB_URL=sqlite+aiosqlite:///./orion.db` | 單機持久化(Cowork 用) |
| **Postgres** | `ORION_DB_URL=postgresql+asyncpg://...` | Production chat-api |

DB schema 在 `storage/db/models.py`。alembic migrations 在 `packages/orion-sdk/migrations/`。

## 三層 token budget(大結果處理)

工具 result 可能超大(完整檔案、大 grep 輸出)。三層處理:

| Layer | 觸發 | 行為 |
|---|---|---|
| **Layer 1**:inline | < 100KB | 直接放訊息內 |
| **Layer 2**:tombstone | >= 100KB | 訊息內留 placeholder(`(omitted 250KB — see tool_results/abc.json)`),完整 result 寫 disk |
| **Layer 3**:compact | total messages > context window threshold | auto/reactive compact,見 [compaction.md](./compaction.md) |

讀取時(resume / 後續 turn 引用):caller 主動讀 tool_results 檔還原。LLM 看到的是 placeholder,知道有東西但不會再吃 token。

## DB schema 核心表

| Table | 用途 |
|---|---|
| `users` | username + bcrypt password + UUID id |
| `sessions` | conversation session metadata |
| `messages` | NormalizedMessage 持久化(JSONL 內容備份) |
| `user_settings` | per-user JSON settings |
| `user_preferences` | per-user feature flags |
| `user_memories` | per-user memory(file-based 的 DB 版,for web chat) |

FK 全部指 `users.id`(Phase 29 修正)。

## File history(Edit/Write 救回)

Phase 19 加:`Edit` / `Write` 之前自動快照原檔到 `file-history/<sha>.txt`,LRU 100 個 file。誤刪可從 SDK API 救回。

## 限制

- Transcript JSONL append-only,沒 GC(會無限長);大檔案靠 OS 自然 rotate(暫無內建)
- SQLite 跨進程同寫會 lock;production 用 Postgres
- 大 tool result 100KB 是寫死 threshold,沒 caller-side config

## 相關

- [compaction.md](./compaction.md) — 三層 budget 之三
- [recovery.md](./recovery.md) — 從 transcript 重建
- [chat-api.md](./chat-api.md) — DB-backed session manager
