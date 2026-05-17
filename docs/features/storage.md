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

### SDK 共用表(`packages/orion-sdk/src/orion_sdk/storage/db/models.py`)

| Table | 用途 |
|---|---|
| `users` | username + bcrypt password + UUID id |
| `sessions` | conversation session metadata |
| `messages` | NormalizedMessage 持久化(JSONL 內容備份);`metadata_json.compacted_out` 旗標做 tombstone soft delete |
| `conversation_metadata` | 每對話 title / 偏好(auto-compact threshold 等) |
| `user_settings` | per-user JSON settings |
| `user_preferences` | per-user feature flags |
| `user_memories` | per-user memory(file-based 的 DB 版,for web chat) |

FK 全部指 `users.id`(Phase 29 修正)。

### Cowork 擴充表(`apps/orion-cowork/sidecar/src/orion_cowork_sidecar/storage.py`)

只在 Cowork host(`~/.orion/sessions/cowork.db`)出現,CLI / chat-api DB 沒這些表:

| Table | 欄位摘要 | 用途 |
|---|---|---|
| `cowork_session_ext` | `session_id` PK / `workspace_dir` / `project_id` / `scheduled_by_id` / `scheduled_by_name` / `starred` | per-session 擴充 metadata。`scheduled_by_*` 在 Sidebar 上顯時鐘 badge;`starred` 拉到 Starred group |
| `cowork_projects` | `id` / `name` / `workspace_dir` / `custom_instructions` / `created_at` | 專案定義。Project chat 用 `workspace_dir` 做 cwd,`custom_instructions` 注入 system prompt |
| `cowork_prefs` | `key` / `value`(KV) | app 級偏好(`default_workspace_dir` / `user_instructions` / `disabled_tools` CSV 等) |
| `cowork_schedules` | (見下) | 排程 + Loop(Phase 31-G) |

### `cowork_schedules`(排程 / Loop 共用)

```sql
id              TEXT PRIMARY KEY    -- UUID
user_id         TEXT NOT NULL DEFAULT 'cowork-local'
project_id      TEXT NULL           -- NULL = user-scope;有值 = project-scope
name            TEXT NOT NULL
cron_expr       TEXT NOT NULL       -- 5-field cron
trigger_type    TEXT NOT NULL       -- 'skill' | 'prompt'
payload         TEXT NOT NULL       -- skill name 或 prompt text
enabled         INTEGER NOT NULL DEFAULT 1
last_run_at     REAL NULL
next_run_at     REAL NULL           -- scheduler 用這個排序
last_run_session_id  TEXT NULL
last_run_status TEXT NULL           -- 'ok' | 'error' | 'skipped'
last_error      TEXT NULL
model_provider  TEXT NULL           -- snapshot 排程建立時的 model
model           TEXT NULL
workspace_dir   TEXT NULL           -- project-scope 自動帶
created_at      REAL NOT NULL
updated_at      REAL NOT NULL
target_session_id  TEXT NULL        -- ★ NULL = Schedule(開新 session);有值 = Loop(綁該 session)
```

**Schedule vs Loop 區別只在 `target_session_id`**:scheduler `_execute_schedule` 看到 NULL 就 `conversation.create + send`(開新對話),有值就 `conversation.send` 送回原對話接續(context 累積)。

Index:`(enabled, next_run_at)` 給 tick query、`project_id` / `target_session_id` 各 join 用。

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
