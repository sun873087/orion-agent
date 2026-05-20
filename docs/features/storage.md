# Storage

對話 / 大結果 / 使用者資料的持久化。

**實作位置**:`packages/orion-sdk/src/orion_sdk/storage/`

## 三層 store

| 層 | 何時用 | Backend |
|---|---|---|
| **Session DB** | 對話 history、metadata | SQLite(CLI / Cowork)/ Postgres(chat-api production) |
| **Blob store**(content-hash) | Image / attachment / large tool result | `~/.orion/blobs/<sha256>`(file system) |
| **File history snapshots** | Edit / Write 工具寫檔前的舊內容(給 undo) | `~/.orion/sessions/<sid>/file-history/<hash>.snap` |

## Session DB schema

```sql
sessions
  id (PK) | title | provider | model | started_at | last_active_at | ...

messages
  id (PK) | session_id (FK) | role | content_json | message_index | created_at
  -- content_json 是 NormalizedMessage 結構(text + tool_use + tool_result blocks)
```

Cowork 加擴充表:

```sql
cowork_session_ext
  session_id (PK / FK) | workspace_dir | project_id | resolved_cwd
  plan_mode_status | plan_id | plan_file_path | plan_content
  budget_usd_cap | budget_exceeded | cumulative_cost_usd
  auto_compact_enabled | auto_compact_threshold | ...

cowork_projects
  id | name | workspace_dir | system_prompt | created_at | ...

cowork_schedules
  id | name | cron | session_id | enabled | last_fired_at | ...
```

跨 SQLite / Postgres 一份 SQLAlchemy ORM。

## Three-layer budget

`storage/budget.py` 防 LLM 訊息爆掉 context / 帳單:

1. **Per-message**:單條訊息 token 上限(default 32K)
   - 超 → truncate + warning(LLM 看到 truncated marker)
2. **Per-session**:session 累積 token 上限
   - 超 → trigger compact(strict 模式擋)
3. **Per-user**(Cowork)/ **per-org**(chat-api)月度 cost cap
   - 超 → 拒新 request,UI 提示

## Large tool result handling

LLM tool 回大結果(`Read` 1MB 檔)— **不**全塞 message_content:

```
tool_result.text:
  "[Saved to blob:sha256-abc123,12345 bytes,first 1000 chars below]
   Tail of result: ..."
```

LLM 看到 truncated preview + blob handle,需要時 Read tool 拉 blob full content(再貼進對話)。

## Blob store

`~/.orion/blobs/<sha256-prefix>/<sha256-suffix>` — content-addressed,跨 session dedup。Cowork
attachment / Edit snapshot 都走這。Cleanup 跑 `cleanup_orphan_blobs`(掃 messages.content_json
找 blob ref,沒 ref 的刪)。

## 設計取捨

- **SQLite / Postgres 一份 schema**:用 SQLAlchemy async,不寫 raw SQL。要 backend-specific 優化未來再說
- **Blob content-hash**:同檔反覆 attach → 自動 dedup(節 disk)
- **File-history per-session**:不跨 session dedup,簡化清理(session 刪 → 對應 file-history 整批刪)

## 限制 / 已知問題

- **No DB migration 系統(SDK)**:schema 變化用 `Base.metadata.create_all`(idempotent)+ manual alter
- **Blob GC 是手動 cron**:`maintenance.cleanup_blobs` RPC,沒自動排程
- **Cowork SQLite WAL 殘留**:crash 後可能 `cowork.db-shm` / `-wal` 沒清,下次啟動回放

## 未來方向

- **Alembic migration**:正式 production-ready migration
- **Auto blob GC**:整入 maintenance task(每天 / 每週跑)
- **Blob cold storage**:>90 天 blob 壓進 single archive(S3 / glacier)
- **Encrypted blob**:`secrets.enc` 之類加密用 master key

## 看完繼續

- [`../architecture/runtime-layout.md`](../architecture/runtime-layout.md) — file system layout
- [recovery.md](./recovery.md) — 從 DB resume session
- [memory.md](./memory.md) — memory 是 markdown,不是 DB
