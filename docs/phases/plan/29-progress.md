# Phase 29 進度交接(2026-05-13 中斷)

**中斷原因**:`.venv/lib/python3.12/site-packages/*.pth` 被 iCloud / Finder 加上 macOS
`UF_HIDDEN` flag,Python `site.py` 跳過所有 .pth → editable install 失效,test 全跑
不起來。已用 `chflags nohidden` 暫解,但 `uv run` 會 re-sync 又被打回 hidden,跑
測試時必須先 `chflags nohidden .venv/.../site-packages/*.pth` + `uv run --no-sync`。

→ user 決定把專案搬離 iCloud 同步路徑(`~/Desktop` 不要,挪 `~/dev/` 或類似)
   再繼續 Phase 29 收尾。

## 已完成

| # | 任務 | 變更檔案 |
|---|---|---|
| 1 | Audit | — |
| 2 | Auth 層 sub=user.id | `api/src/orion_agent/api/auth.py`(完整改寫)、`api/src/orion_agent/api/routes/auth.py` login 兩條路徑改 `issue_token(user_id=…, username=…)` |
| 3 | `GET /me` endpoint | `api/src/orion_agent/api/deps.py` 加 `current_identity` dep、`api/src/orion_agent/api/routes/auth.py` 加 route + `MeResponse` |
| 4 | Alembic migration | `api/src/orion_agent/storage/db/alembic/versions/0004_backfill_user_id_fk.py`(新檔) |
| 5 | SQLite PRAGMA FK=ON | `api/src/orion_agent/storage/db/engine.py`(改 `create_db_engine` + 加 connect listener),`api/src/orion_agent/api/session_manager_db.py` 註解更新 |

## 進行中(7 已部分完成)

| # | 任務 | 狀態 |
|---|---|---|
| 7 | 測試更新 | `tests/unit/api/test_auth.py` 已完整重寫(10 個 case,含 legacy token 拒絕、/me round-trip);`test_sessions.py` 改了一處 `body["user_id"] == dev_user_id("alice")`;`test_oauth_routes.py` 改了 `test_token_payload_stored_as_json` 一個 case。**還沒跑過完整 suite**,可能還有別的測試該改。 |

## 未開始

| # | 任務 | 待辦 |
|---|---|---|
| 6 | Frontend | 還沒看 `frontend/`。login response 多了 `username` field,要存 localStorage / context;header / sidebar 顯示要從 localStorage 拿 username 而非解 JWT。 |
| 8 | 跑全測試 + 修殘留 | 需 `chflags nohidden` 後 `uv run --no-sync pytest tests/unit/ -q`。先重點看 `tests/unit/api/`、`tests/unit/db/`、`tests/unit/storage/`、`tests/unit/mcp/test_oauth*` (沒看過)。 |
| 9 | Phase 29 完工筆記 | `docs/phases/done/29-…md`。 |

## 接手後第一步建議

1. 確認專案已搬離 iCloud 同步路徑;`.pth` 不再被打 hidden flag。
2. `cd <new-path>/api && make install`(uv sync + reinstall editable)。
3. `uv run pytest tests/unit/ -q` 看整體狀況。**重點關注**:
   - `tests/unit/api/test_user_settings_routes.py` — 走完整 register → login → DB FK on 路徑,理論上 Phase 29 改完應該 pass。若 fail 看是否 FK violation。
   - `tests/unit/api/test_session_delete_cleanup.py` — 已正確用 `_new_user` 拿 UUID,應該沒事。
   - `tests/unit/api/test_chat_ws.py` — login 走 dev fallback,user_id 變 uuid5。沒有對 user_id 做字串斷言,理論上 OK。
   - `tests/unit/api/test_oauth_routes.py` — 還有 `test_per_user_token_isolation` 等可能要對 backend key。檢查是否需改。
   - `tests/unit/api/test_memories_routes.py` — 看是否依賴 username 當 directory key(`users/alice/memory/`)。若依賴用 username 而非 user_id,影響很大。
4. 跑完 unit,加一個 **FK enforcement 正向測試**:設 ORION_DB_URL 起 SQLite,register alice,login,寫 user_settings,確認沒爆。再試 user_id 寫死亂猜的 UUID(不存在 users.id),確認 raises IntegrityError。
5. Frontend `frontend/src/` 找 token decode / username 來源:
   ```bash
   grep -rn "jwt\|atob\|user_id\|username" frontend/src/
   ```
   把 login response 的 `username` 存進 store/context,顯示處改用它。
6. 寫 `docs/phases/done/29-fix-auth-userid-fk.md`,內容大致:
   - 改了什麼(sub=user.id、/me、dev uuid5、PRAGMA on、migration 0004)
   - Token rotation 採方案 (b):缺 `username` claim 的舊 token 一律 401
   - Phase 28 手動 cascade 保留為顯式安全網

## 關鍵設計決策(交接記憶)

- **Dev mode user_id 是 `uuid5(NAMESPACE_DNS, username)`**:deterministic、跨重啟一致。
  測試斷言用 `from orion_agent.api.auth import dev_user_id` 而非 hardcode UUID。
- **Token rotation 走 schema 而非換 secret**:`verify_token_full` 要求 `username` claim
  存在,沒有就 `InvalidTokenError`。dev 環境無感(重 login),production 公告即可。
- **Migration 0004 兩條 NOT IN / IN guard**:只動 user_id 不在 users.id 但在
  users.username 的 row;已是 UUID 的新資料不動,孤兒 row 不動。
- **手動 cascade 保留**:`DbSessionManager.delete` 仍照刪 messages / metadata,FK on
  是安全網。理由:顯式 > 隱式,跨 DB 一致。

## 還沒驗的風險

- migration 0004 對 SQLite 在 FK on 狀態下跑 UPDATE 會不會 violate(因為 user_id
  欄位 column 本身就是 FK)。**可能要**在 migration 內 `PRAGMA foreign_keys=OFF`,
  跑完再 `ON`。但 alembic env.py 用的是 sync URL,連線本來就沒設 listener,可能
  已經是 off 狀態 — 接手時確認。
- `frontend/` 還沒看,可能有其他依賴舊 user_id 形式(localStorage / state machine /
  WS 連線參數)的程式碼需要動。
