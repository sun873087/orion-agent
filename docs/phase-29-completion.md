# Phase 29 — Auth user_id ↔ DB FK 對齊 完工記錄

**完成日期**:2026-05-14
**Plan doc**:`docs/phases/29-fix-auth-userid-fk.md`(原 `docs/phases/plan/29-...`,完工後搬出)
**狀態**:✅ **907 unit tests passed, 2 skipped**(baseline 902 + 新增 FK enforcement 2 + 修復 memories routes 3),frontend `tsc --noEmit` 0 error。

audit 時發現 schema FK 指 `users.id`(UUID)但 JWT `sub` 從 Phase 6 起一直是 username 字串。SQLite `PRAGMA foreign_keys` 預設 `OFF` 才沒爆,Postgres 上會直接死;Phase 28 第一版打開 PRAGMA 時 10+ 個 test 瞬間 fail 才暴露問題,Phase 28 revert PRAGMA 改手動 cascade 繞過,Phase 29 收齊。

---

## 速覽

- **前置 Phase**:Phase 6(FastAPI auth)、Phase 7(register/login)、Phase 14(user_settings)、Phase 28(發現此 bug 並 workaround)
- **主要交付物**:
  - JWT `sub` 改成 `users.id`,`username` 走獨立 claim
  - `GET /me` endpoint(回 user_id + username,frontend 顯示用)
  - SQLite connect listener 打開 `PRAGMA foreign_keys=ON`
  - Alembic migration 0004 backfill 既存 row 的 user_id 從 username → UUID
  - 舊版 token rotation 走 schema(必含 username claim),缺者一律 401
  - Frontend Login 改用 response.username 而非 form input
  - FK enforcement 正向 + 負向測試

## 1. 為何要做

Phase 6 初版 dev mode `sub=username` 沒問題(沒 DB)。Phase 7 加 DB-backed
register/login,User row 用 `uuid4` 當 id;但 `issue_token()` 仍把 username
塞進 `sub`,沒同步改。

接著 Phase 13/14 寫 user_preferences / user_settings,schema 用
`ForeignKey("users.id", ondelete="CASCADE")`。`current_user` 取 `sub`(是
username)拿來當 FK target — 跟 `users.id` 對不起來。

SQLite `foreign_keys` PRAGMA 預設 `OFF`,所以 dev / 多數 test 環境沒爆。
但:
- Postgres 上 FK 強制 on,user_settings.user_id="alice" 但 users.id=<uuid>,
  寫就死。
- 安全網全壞:刪 user 不會 cascade 清 user_settings(FK 不檢)。
- Phase 28 的 cascade delete 全靠手動 SQL,不是 FK 本身。

定時炸彈,Phase 29 收齊。

## 2. 任務拆解(全數完成)

- [x] `api/auth.py`:`sub` 放 `user.id`(UUID),`username` 獨立 claim;
      `dev_user_id(username) = uuid5(NAMESPACE_DNS, username)` 給無 DB 環境
- [x] `api/routes/auth.py`:`/auth/login` 兩條路徑(DB / dev)都改
      `issue_token(user_id=..., username=...)`;加 `GET /me`
- [x] `api/deps.py`:加 `current_identity` dependency 回 `Identity` 物件
- [x] `storage/db/engine.py`:SQLite engine connect listener 開
      `PRAGMA foreign_keys=ON`(每條新 connection)
- [x] `alembic/versions/0004_backfill_user_id_fk.py`:對 sessions /
      user_settings / user_preferences 跑 `UPDATE user_id = (SELECT id
      FROM users WHERE username = <table>.user_id)`,只動「current user_id
      不在 users.id 但在 users.username」的 row
- [x] `api/session_manager_db.py` 註解更新(FK 開啟後手動 cascade 改當
      安全網)
- [x] `tests/unit/api/test_auth.py` 重寫(10 case,含 legacy token 拒絕、
      /me round-trip)
- [x] `tests/unit/api/test_sessions.py`、`test_oauth_routes.py` 對
      `dev_user_id("alice")` 斷言
- [x] `tests/unit/api/test_memories_routes.py` fixture 抓 login.user_id,
      五處硬碼路徑改 UUID
- [x] `tests/unit/api/test_session_delete_cleanup.py:132` polish 用
      `dev_user_id("alice")`
- [x] `tests/unit/storage/test_fk_enforcement.py` 新增(正 + 負)
- [x] `frontend/src/components/Login.tsx`:response type 加 `username`,
      `setAuth` 用 `resp.username` 而非 form input

## 3. 設計決策

### Token rotation:換 schema 而非換 secret

兩條路:
- **(a) 換 ORION_JWT_SECRET**:所有舊 token 簽名驗證失敗 → 401。簡單但
  signature error 訊息可能對 user 不友善;另若 secret 之前是 random
  生成(沒設 env),restart 就會 rotate,變數行為。
- **(b) verify 改要求 `username` claim**:沒有 → `InvalidTokenError`,
  401 訊息明確("token missing 'username' claim — please re-login")。

選 (b)。Dev 無感(空 password 重 login 即可),production 公告 user 重
login。

### Dev fallback user_id:uuid5 而非 uuid4

`dev_user_id(username) = uuid5(NAMESPACE_DNS, username)` — 同 username
永遠拿到同 UUID。理由:
- 跨重啟一致:測試 / dev 起新 server,既存 fs / DB 資料 user_id 對得上。
- 測試斷言可重現:`from orion_agent.api.auth import dev_user_id; assert
  body["user_id"] == dev_user_id("alice")` — 不必硬碼 UUID。

### 手動 cascade 保留為安全網

`DbSessionManager.delete` 仍照刪 messages / metadata 而沒只靠 FK
cascade。理由:
- **顯式 > 隱式**:讀 code 看得到清啥;FK cascade 散在 schema。
- **跨 DB 一致**:Postgres FK ON 永遠,SQLite 看 PRAGMA;不依賴 PRAGMA
  狀態。
- **debug 友善**:cascade 鏈一長就難追,手動清狀態更可控。

### Migration 0004 雙重 guard

`UPDATE ... WHERE user_id NOT IN (SELECT id FROM users) AND user_id IN
(SELECT username FROM users)`:
- 第一條:已是 UUID 的新資料(Phase 29 之後寫入)不動,冪等。
- 第二條:孤兒 row(既不是 users.id 也不是 users.username)不動,
  保留給人工檢查 — 通常是 dev 環境殘留,清掉風險高。

### CLI default_user_id "default" 不動

`memory/paths.py:default_user_id()` CLI fallback 仍回 `"default"`(非
UUID)。CLI 不打 DB FK,只寫 fs 檔案,不影響本 phase。若 CLI 未來要
跟 DB-backed user 整合再另設 phase。

## 4. 驗收標準

```bash
cd api && uv run pytest tests/unit/ -q
# 907 passed, 2 skipped(含本 phase 新增 test_fk_enforcement.py 2 條)

cd frontend && npm run typecheck
# 無 type error
```

FK enforcement 正向 + 負向兩條:
- `test_fk_violates_when_user_id_not_in_users` — 寫 user_settings
  但 user_id 是亂造 UUID → `IntegrityError`(若 PRAGMA 沒開會錯誤
  pass)。
- `test_fk_passes_with_real_user_id` — user_id 是真 users.id →
  寫入正常。

## 5. 未驗 / 後續

- **Postgres 真實環境跑 migration 0004**:本地僅 SQLite 驗過。Postgres
  上 FK 永遠 enforce,UPDATE 過程中(user_id 還沒切完)會不會 violate
  待實測。需要的話 migration 內 `SET CONSTRAINTS ALL DEFERRED` 包起來。
- **舊 fs 路徑遷移**:`~/.orion/users/alice/memory/...` 等仍以 username
  當 directory key 的 production 資料,Phase 29 後 backend 找不到(改用
  UUID)。本 phase 沒做 fs migration 工具,留給後續 phase 或一次性
  one-off script。
- **CLI default_user_id**:仍是字串 "default",不在本 phase scope。
