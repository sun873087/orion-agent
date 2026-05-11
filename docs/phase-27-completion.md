# Phase 27 — DB-backed message persistence(`messages` 表終於不是 dead schema)完工記錄

**完成日期**:2026-05-12
**Plan doc**:無(對話內定案,未開正式 plan 檔)
**狀態**:✅ **895 unit tests passed, 2 skipped**(本 phase 新增 **8 tests**),mypy --strict 修改檔 0 issues。

## 動機(訂正版)

User 觀察:`ORION_DB_URL=sqlite+aiosqlite:///./orion.db` 啟動 server 後,session `59b3106b-…` 目錄裡看不到 `transcript.jsonl` 但前端仍能顯示歷史訊息 → 「訊息存哪了?」

**第一輪錯誤診斷**(寫進原始 commit `5638094` message,事後實機驗證證實**不正確**):

> 「`messages` 表沒寫入路徑,訊息只在 JSONL;那個 session 沒 JSONL 表示只在 in-memory cache,server 重啟就 lose。」

實機驗證後發現:
- 訊息**一直**透過 `Conversation.send` → `SessionStorage.record_message` 寫進 `transcript.jsonl`(Phase 2 起就有)
- `DbSessionManager.get()` cache miss 時走 `load_session()` 從 JSONL 重建 Conversation — **server 重啟看到歷史訊息一直 work**,不需要 in-memory cache
- 我看到的 `59b3106b-…` 空目錄純粹是「那 session 從沒實際發過訊息」(只 metadata 建好,custom_instructions="2222"),不是訊息消失

**Phase 27 真正的價值**(不是修救 data loss,是補上長期未完工的 schema):

- `storage/db/models.py:175-203` 早就定義 `messages` 表(Phase 7 spec 寫的)
- 但**整個 src/ grep 沒有任何程式碼 INSERT 進去** — write path 從未實作 → schema 一直是 dead
- DB messages 表的存在意義:
  1. SQL 可查詢(WHERE role / COUNT / ORDER BY / 全文搜尋 `raw_text`)— 將來訊息搜尋功能需要
  2. Postgres 多 pod 部署(Phase 7c K8s)— JSONL 是 local fs 不能跨 pod,DB 才可靠
  3. ACID + transaction 給 audit 用,比 JSONL append best-effort 強

Phase 27 補上 messages 表的 write/read path。**對 user 而言行為等價**(訊息在 JSONL 一直能 resume);**對未來 scale-out / 查詢 / 多 pod 是必要鋪路**。

## 交付清單

### 修改檔

| 檔 | 變更 |
|---|---|
| `storage/session.py` | SessionStorage.open 加 `db_engine` 參數;`record_message` 在有 engine 時 dual-write JSONL + INSERT `messages` 表;FK / DB down 例外只 log warning 不擋 JSONL |
| `storage/resume.py` | 抽 `fetch_db_messages(sid, engine)` async 函式;`load_session` 加 `prebaked_messages` 參數讓 caller 預先 await 拿 DB messages 再傳進(避開 `:memory:` SQLite sync engine 看不到 async 寫入的 issue);transitions / replacements 永遠走 JSONL |
| `core/conversation.py` | Conversation 加 `db_engine: object \| None` 欄位;`_ensure_storage` 把 engine 傳給 SessionStorage.open |
| `api/session_manager_db.py` | `create` / `get`(cache miss resume)兩條路徑都注入 `engine` 給 Conversation;resume 改先 `await fetch_db_messages` 拿 prebaked,再 `to_thread(load_session, ...)` |
| `docs/PROJECT_LAYOUT.md` | sessions § 補「DB messages 表(Phase 27 之後)」段,說明 dual-write + resume 優先序 |

### 新增 tests/unit/storage/test_db_message_persistence.py(8 cases)

```
test_record_message_inserts_into_db            # engine 提供 → DB 收到 row
test_jsonl_still_written_when_engine_provided  # JSONL 仍是 audit log,不因有 DB 而停寫
test_load_session_reads_db_when_messages_exist # resume 走 DB
test_load_session_falls_back_to_jsonl_when_db_empty  # DB 空 → JSONL legacy 補救
test_load_session_no_engine_uses_jsonl         # CLI / no-engine 純走 JSONL(向後相容)
test_message_with_tool_use_block_roundtrips_via_db  # 複雜訊息 structure 經 DB 來回保留
test_db_insert_failure_does_not_break_jsonl    # DB down(engine disposed)→ 不擋 JSONL
test_replacements_still_jsonl_only             # transitions/replacements 仍只 JSONL
```

## 設計決策

### 1. 為何 dual-write 而不是純 DB
JSONL 仍是 events audit log:
- transitions / replacement decisions 沒有對應 DB 表(本 phase 範圍限 messages,搬完整 schema 是更大的 work)
- JSONL 是 append-only 文字,易於 debug / grep / 復原
- migration 風險低 — 既有 JSONL session 仍可 resume

### 2. resume 路徑採 prebaked_messages 而非 load_session 自己讀 DB
`load_session` 是 sync(被 `asyncio.to_thread` 包用)。要從 sync context 讀 async engine 的 SQLite `:memory:` 行不通(per-connection,sync engine 看不到 async engine 的記憶體 DB)。改成:
- caller(DbSessionManager)在 async context 先 `await fetch_db_messages(sid, engine)` 拿到 messages
- 再 `to_thread(load_session, sid, prebaked_messages=messages)` 跑 sync JSONL 補 transitions / replacements
- 這把 sync/async 邊界畫清楚,production Postgres 跟 test `:memory:` SQLite 都通

### 3. DB INSERT 失敗 log warning,不 raise
- FK violation(session row 不存在)/ DB down 都不該破壞 conversation flow
- JSONL 是 canonical 確保訊息不掉,DB 是 query mirror
- 真正寫不進 DB 的後果是「server 重啟後 resume 從 JSONL,跟 Phase 27 之前一樣」— graceful degradation

### 4. content_json 直接存 list[dict] / str,不存 serialize 字串
- `JSON` 欄位類型(SQLite TEXT / Postgres JSONB)— 讓 DB-side query / index 能力可用
- `raw_text` 欄位另存 plain text(SQL search-friendly,Phase 28+ 全文搜尋可用)
- resume 時 `_message_from_dict` 已能處理 dict 形式 content,沒額外解析

### 5. fetch_db_messages 在 caller async context 跑,不在 sync load_session 裡
- 避免 sync engine 對 `:memory:` SQLite 不通的問題(設計決策 #2 的延伸)
- load_session 保持純 sync API,既有 caller(`Conversation.resume`)不必改

### 6. JSONL `record_message` 一定先寫 → DB INSERT 才跑
順序保證:DB INSERT 失敗時 JSONL 已落地,canonical 安全。

## 不做的(留給未來 phase)

- **transitions / replacements 進 DB**:需要新表 + migration,本 phase 限 messages
- **舊 JSONL session 一次性 migrate 進 DB**:lazy fallback 已能讀,沒急迫性
- **刪 JSONL** 改純 DB:JSONL 仍是 audit log + transitions/replacements 載體,不刪
- **Conversation.resume() (CLI)** 也用 DB:CLI 模式預設無 engine,維持 JSONL only
- **`stats.sync_stats` 同步 n_messages 改成 `SELECT COUNT(*)`**:目前還是用 `len(state_messages)`,夠用

## Verification

```bash
cd orion-agent/api/

# 新測試集
.venv/bin/python -m pytest tests/unit/storage/test_db_message_persistence.py -xvs
# → 8 passed

# 全套不退步
.venv/bin/python -m pytest tests/unit/
# → 895 passed, 2 skipped(+8 vs Phase 19 完工時的 887)

# typecheck 修改檔
.venv/bin/python -m mypy \
    src/orion_agent/storage/session.py \
    src/orion_agent/storage/resume.py \
    src/orion_agent/core/conversation.py \
    src/orion_agent/api/session_manager_db.py
# → Success: no issues found in 4 source files
```

### 手動驗證

```bash
# 用 SQLite file 啟動 server
ORION_DB_URL=sqlite+aiosqlite:///./orion.db .venv/bin/orion serve --port 8000

# 前端送幾則訊息,然後查 DB
.venv/bin/python -c "
import sqlite3
con = sqlite3.connect('./orion.db')
for row in con.execute('SELECT role, substr(raw_text, 1, 40) FROM messages ORDER BY created_at'):
    print(row)
"
# 預期:看到真實 user / assistant 訊息(Phase 27 之前這裡是空的)

# 重啟 server 後再開該 session,resume 會優先讀 DB messages(Phase 27 之前走 JSONL,效果等價)
```

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–19 既有 | 887 | 全綠不動 |
| **Phase 27 db persistence** | 8 | INSERT / JSONL 共存 / DB resume / JSONL fallback / no-engine / ToolUseBlock roundtrip / failure isolation / replacements JSONL-only |
| **總計** | **895 passed / 2 skipped** | mypy 修改檔 0 issues |

## 風險與緩解

| 風險 | 緩解 |
|---|---|
| DB messages 與 JSONL messages drift(雙寫不一致) | 順序保證:JSONL 先,DB 後;DB 失敗 log warning,JSONL canonical;resume 優先 DB 但 fallback JSONL |
| Postgres `:memory:`-style 測試問題擴散 | `fetch_db_messages` 在 async context 跑,sync load_session 不碰 DB(設計決策 #2) |
| 既有 session(只有 JSONL)在 SQLite 啟用後變不可讀 | `fetch_db_messages` 回 None → load_session 自動走 JSONL fallback,test_load_session_falls_back_to_jsonl_when_db_empty 鎖 invariant |
| 大量訊息 INSERT 拖慢 record_message | 每筆獨立 commit,no batch;若日後吞吐成問題可改 batch insert 或 background flush |
| Conversation.db_engine 用 `object` type-hint(避免循環 import)→ runtime 拿到非 AsyncEngine 物件不會 error | `_ensure_storage` `isinstance(...AsyncEngine)` 才傳給 SessionStorage;非預期型別退化成「無 DB」靜默 |

## 實作中發現的坑

### 1. `db_session()` 不自動 commit
第一版 `_db_insert_message` 只 `db.add(row)` 沒 `await db.commit()`,測試看 DB 全空才發現。`db_session` 是 plain context manager,不在 exit 時 commit(這是合理設計,讓 caller 控制 transaction 邊界)。

### 2. SQLite `:memory:` per-connection 行為
第一版 `_load_messages_from_db_sync` 用 sync `create_engine` 連同 URL,測試報「no such table: messages」。`:memory:` SQLite 每個 connection 是獨立 DB,async engine 寫進去的東西 sync engine 看不到。改成 caller 預先 async 撈 messages 再 sync 補 JSONL。

### 3. SQLite 預設 FK 關
第一版 test_db_insert_failure_does_not_break_jsonl 假設 messages.session_id FK 會擋住孤兒 INSERT,結果 SQLite 預設不 enforce FK → INSERT 成功,測試 fail。改用「dispose engine 模擬 DB down」測 graceful degradation。

### 4. Auto-repair 加 synthetic tool_result 影響訊息計數
test_message_with_tool_use_block_roundtrips_via_db 寫一則 assistant message 含 dangling ToolUseBlock,`validate_and_repair_messages` 自動補一則 synthetic error tool_result → snapshot.messages 從 1 變 2。測試斷言改 check 第一則,不假設總數。

### 5. ⚠ 初版動機完全 misframe(訂正記錄)
原 commit `5638094` message + 本 doc 第一版「動機」段宣稱「Phase 27 之前 server 重啟會 lose 訊息、依賴 in-memory cache」。**這是錯的**。User 用「重啟 API 還看到 message」的觀察戳破:

- `Conversation.send` 從 Phase 2 起就把每筆訊息寫進 `transcript.jsonl`
- `DbSessionManager.get()` cache miss 走 `load_session()` 讀 JSONL 重建 — **重啟 resume 一直 work**,跟 DB 啟用無關
- 我把「`messages` 表是空的」誤推成「訊息會遺失」,沒去 trace JSONL 寫入路徑就下結論

教訓:看到「DB 空」不等於「資料消失」 — orion 是 dual persistence(fs JSONL canonical + DB metadata),要兩條路都查清才能下診斷。**之後動到任何 storage 議題都先把兩條路徑都驗一遍**。

Phase 27 真正解決的是「`messages` 表是 dead schema」這個技術債,**不是**修救資料遺失。對 user 行為等價,對未來 SQL 查詢 / 多 pod / audit 是必要鋪路(見「動機」訂正段)。
