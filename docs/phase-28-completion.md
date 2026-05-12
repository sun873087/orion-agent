# Phase 28 — 介面刪 session 真的清光所有相關資料 完工記錄

**完成日期**:2026-05-12
**Plan doc**:無(對話內定案)
**狀態**:✅ **901 unit tests passed, 2 skipped**(本 phase 新增 **6 tests**),mypy --strict 修改檔 0 issues。

User 觀察:從前端介面按 delete session 後,`~/.orion/sessions/<sid>/` 目錄沒被清掉,DB `conversation_metadata` row 也還在。「使用者都介面刪了,你要我去刪嗎?」對 — 該系統幫使用者清,不是反過來。

## 三個疊在一起的 bug

1. **fs 沒清**:`DbSessionManager.delete` 只 `DELETE FROM sessions WHERE id=?`,沒碰 `~/.orion/sessions/<sid>/`(transcript.jsonl / file-history / tool-results / workspace 全留)
2. **DB CASCADE 失效**:`models.py` 雖寫 `ondelete="CASCADE"`,但 SQLite 預設 `PRAGMA foreign_keys=OFF` → CASCADE 是空話。`messages` / `conversation_metadata` 不會跟著 sessions row 刪
3. **in-memory `SessionManager.delete`** 純 dict pop,沒清 fs(CLI / no-DB 模式也有 transcript)

## 交付清單

### 修改檔

| 檔 | 變更 |
|---|---|
| `storage/db/engine.py` | docstring 註明 SQLite 預設 FK off + 解釋為何**不啟用 PRAGMA**(見「為何不打開 PRAGMA」段)|
| `api/session_manager.py` | 加 `_rmtree_session_dir(sid)` 共用 helper;`SessionManager.delete` 加 fs cleanup |
| `api/session_manager_db.py` | `delete` 改手動 cascade(自己 `DELETE` `messages` + `conversation_metadata` + `sessions`)+ fs cleanup;新增 `sweep_orphan_fs_sessions()` 方法 |
| `api/app.py` | lifespan DB 啟動完 call `sweep_orphan_fs_sessions()` 清掉歷史殘留;失敗 log 不擋 startup |

### 新增 `tests/unit/api/test_session_delete_cleanup.py`(6 cases)

```
test_db_delete_cascades_messages_and_metadata    # 三表一起清,手動 cascade 真的有效
test_db_delete_removes_fs_dir                     # ~/.orion/sessions/<sid>/ 整個目錄消失
test_in_memory_delete_removes_fs_dir              # CLI / no-DB 模式同樣清 fs
test_orphan_sweep_removes_dir_without_db_row      # startup 清歷史殘留
test_orphan_sweep_safety_gate_when_users_empty    # DB 空(疑似 init 失敗)→ no-op 不誤砸
test_orphan_sweep_ignores_non_uuid_dirs           # 非 UUID 形式目錄(user 手動建的)不動
```

## 為何不打開 PRAGMA

第一版實作打開 `PRAGMA foreign_keys=ON`,跑全套測試時暴露**全系統的 FK 設計 bug**:

- JWT token `sub` 存的是 username(`auth.py:51-60`)
- `current_user()` 把這個 username 字串直接當 user_id 用
- 但 `user_settings.user_id` / `sessions.user_id` 等 FK 是指向 `users.id`(auto-UUID)
- 整個系統一直靠 「SQLite FK off」掩護才能跑 — Postgres 部署其實會炸(production blind spot)

修這個要動 auth + 所有 routes,scope 遠超 Phase 28。**暫時 revert PRAGMA**,改用「手動 DELETE FROM messages + conversation_metadata」的方式做 cascade — Postgres 即使 FK 有效也照做不會錯,功能等價。

但這個 FK 設計問題本身值得**獨立 phase 修**:可以選把 `sub` 改成 user.id,或把 FK 改成參照 username + unique 約束。本 phase 不做。

## 設計決策

### 1. 手動 cascade 而不是依賴 FK
見「為何不打開 PRAGMA」。直接 `DELETE FROM messages WHERE session_id=?` + `DELETE FROM conversation_metadata WHERE session_id=?` + `DELETE FROM sessions WHERE id=?`。三條 SQL 都在同一 `async with db_session` 內 commit 才回 `True`。

### 2. fs cleanup 抽共用 helper
`_rmtree_session_dir(sid)` 給 in-memory + DB session manager 共用。`shutil.rmtree(root, ignore_errors=True)` 不擋主流程 — 即使檔案被其他 process 鎖也不會 raise。

### 3. Orphan sweep 安全閘:DB users 表空就不清
**踩過的雷**:DB init 失敗 / migration 未跑時,sessions 表是空的,naive sweep 會把所有 fs sessions 當 orphan 砸光。
**修法**:sweep 前先 `SELECT COUNT(*) FROM users`,= 0 直接 return 0 + log info。等於「DB 沒人在用 = 不可信,別動 fs」。

### 4. Sweep 只清 UUID 形式的目錄
`UUID(child.name)` 解析失敗的目錄(user 手動建的 `my-backup-stuff` 之類)跳過。test_orphan_sweep_ignores_non_uuid_dirs 鎖此 invariant。

### 5. Sweep 失敗不擋 startup
`app.py` lifespan 內 try/except 包 sweep,例外 log warning 不 raise — server 該能在 sweep 出問題時還是啟動。

### 6. delete 回 True 的條件:DB row 真的被刪 OR cache 真的被踢
原邏輯:`return db_deleted or cached is not None`。新邏輯保留同樣語意,但因為新增的 fs cleanup 是 best-effort(目錄不存在也 OK),不影響 return 值。

## REST API 變更

無。`DELETE /sessions/{sid}` endpoint 簽名不變,只是現在真的把資料清光。

## 環境變數

無新環境變數。

## Verification

```bash
cd orion-agent/api/

# 新測試集
.venv/bin/python -m pytest tests/unit/api/test_session_delete_cleanup.py -xvs
# → 6 passed

# 全套不退步
.venv/bin/python -m pytest tests/unit/
# → 901 passed, 2 skipped(+6 vs Phase 27 完工時的 895)

# typecheck 修改檔
.venv/bin/python -m mypy \
    src/orion_agent/storage/db/engine.py \
    src/orion_agent/api/session_manager.py \
    src/orion_agent/api/session_manager_db.py \
    src/orion_agent/api/app.py
# → Success: no issues found in 4 source files
```

### 手動驗證

```bash
# 啟動 server(DB mode)
ORION_DB_URL=sqlite+aiosqlite:///./orion.db .venv/bin/orion serve --port 8000

# 介面跑幾個對話,然後刪一個 session
# 之後檢查:
ls ~/.orion/sessions/        # 對應 <sid>/ 目錄應該不見了
sqlite3 ./orion.db "SELECT COUNT(*) FROM messages WHERE session_id='<sid>'"  # 0
sqlite3 ./orion.db "SELECT COUNT(*) FROM conversation_metadata WHERE session_id='<sid>'"  # 0

# 既有殘留(Phase 28 之前刪的 session 留下的 fs 目錄):server 啟動時自動 sweep
# 看 log: orphan_session_dirs_swept count=N
```

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–27 既有 | 895 | 全綠不動 |
| **Phase 28 delete + cleanup** | 6 | manual cascade / fs rm / in-memory fs rm / orphan sweep / safety gate / 非 UUID 不動 |
| **總計** | **901 passed / 2 skipped** | mypy 修改檔 0 issues |

## 風險與緩解

| 風險 | 緩解 |
|---|---|
| Orphan sweep 把 user 的非 session 目錄砸了 | 只清 UUID 形式 + DB users 表非空(設計決策 #3、#4)|
| Sweep 在 startup 卡 server | 包 try/except,例外 log 不 raise(設計決策 #5)|
| 既有 session 沒對應 user.id 在 DB → 被 sweep | 安全閘:DB users 表非空才 sweep,真實使用者場景必有 user row |
| 手動 cascade 漏寫一張表 → orphan row | 三張表(`messages` / `conversation_metadata` / `sessions`)test 全部斷言為 [];未來加新 session-scoped 表要記得加進 delete() |
| Postgres 部署也走手動 cascade → 重複功夫 | 是的,但功能等價 + 行為一致。FK 真修好(獨立 phase)後可改回 cascade |

## 內部對應原 plan(對話內定義)的差異

| 原計畫 | 差異 | 為何 |
|---|---|---|
| 打開 SQLite PRAGMA `foreign_keys=ON` | **不打開** | 暴露 auth 層 user_id 語意 bug(JWT sub=username,FK 期待 users.id UUID)— 整個系統靠 FK off 才能跑。修這個要另開 phase |
| 用 schema CASCADE 自動清相關表 | 改手動 DELETE 三張表 | 不 PRAGMA 的話 CASCADE 空話;手動寫保證跨 DB 一致 |

## 實作中發現的坑

### 1. 打開 PRAGMA 暴露全系統 FK bug
打開的瞬間 10+ 個既有 user_settings / sessions 測試 fail with `FOREIGN KEY constraint failed`。trace 發現:
- `auth.py:56` 寫 `"sub": username`
- `deps.py:current_user` 把 sub 直接當 user_id 回
- `user_settings.user_id` / `sessions.user_id` 的 FK target 是 `users.id`(UUID),value 是 username
- 整個資料模型靠「SQLite 預設 FK off」當隱形護欄

production 跑 Postgres 會直接 500(雖然可能根本沒人用 user_settings 才沒爆)。Phase 28 不修這個(scope 太大),走手動 cascade 繞過。

### 2. sweep 安全閘的設計
naive sweep:「掃 fs,任何 UUID 目錄不在 DB sessions 表就刪」。但若 DB 剛 init / migration 失敗 / 連線壞,sessions 表會是空的 → 把所有 user 的對話檔砸光。
正確的:**先檢查 DB users 表非空**。users 沒人 = DB 不可信 = 不該動 fs。

### 3. anyio.to_thread.run_sync 對 shutil.rmtree
`shutil.rmtree` 是 sync I/O,直接在 async function 內呼叫會阻塞 event loop。包 `await anyio.to_thread.run_sync(...)` 避免影響其他連線。

### 4. `_rmtree_session_dir` 放 in-memory session_manager.py 給 DbSessionManager import
跨層 import 通常嫌氣味重,但兩個 manager 都需要這個 helper + 行為一致是 invariant,放 `session_manager.py` 由 DB 版 import 比另開 `_cleanup.py` 簡潔。

### 5. delete() 即使 cache miss + DB row 不存在仍跑 fs cleanup
覆蓋這場景:user 用過 session、server 重啟後 cache 已清、user 直接按 delete → DB 還有 row 該刪 + fs 還有目錄該清。同樣覆蓋「session 在 in-memory mode 對話過(寫了 transcript)但沒進 cache 就 delete」邊角案例。
