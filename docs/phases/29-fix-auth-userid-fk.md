# Phase 29:修 auth user_id 與 DB FK 的型別不一致

## 速覽

- **預計時程**:1-2 天
- **前置 Phase**:Phase 7(DB schema)、Phase 28(發現此 bug 並做 workaround)
- **觸發來源**:Phase 28 第一版實作打開 SQLite `PRAGMA foreign_keys=ON` 時,10+ 個既有測試瞬間 fail with `FOREIGN KEY constraint failed`。trace 後發現是系統性設計 bug,scope 太大,Phase 28 revert PRAGMA 改用手動 cascade 繞過。本 plan 把根本問題記下來等獨立修。
- **狀態**:📝 spec only,**未實作**

## 1. Bug 描述

### 現況

JWT 簽發路徑(`api/auth.py:56`):
```python
"sub": username,    # ← 存 username 字串(如 "alice")
```

驗證路徑(`api/deps.py:current_user`):
```python
return verify_token(creds.credentials)   # ← 回 sub,即 username
```

所有 routes 拿這個 `user_id: str` 字串往 DB 寫:
```python
# api/routes/user_settings.py
user_id: Annotated[str, Depends(current_user)],
db.add(UserSetting(user_id=user_id, key=..., value=...))
```

但 schema(`storage/db/models.py`)所有 user-scoped FK 都指向 `users.id`(auto-UUID):
```python
class User:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    username: Mapped[str] = mapped_column(String(64), unique=True)

class Session:           # line 62
    user_id: ForeignKey("users.id", ondelete="CASCADE")
class UserSetting:       # line 111
    user_id: ForeignKey("users.id", ondelete="CASCADE")
class UserPreference:    # line 141
    user_id: ForeignKey("users.id", ondelete="CASCADE")
```

**FK 期待 users.id(UUID),route 寫入 username 字串 → mismatch**。

### 為何沒爆

- **SQLite 預設 `PRAGMA foreign_keys=OFF`**:FK 不 enforce,INSERT 過了當沒事
- **Postgres / MySQL** 預設 enforce → production 跑這兩種會直接 500 in INSERT
- 既有 unit / integration test 全 SQLite in-memory,FK off 把問題藏住

### 影響

| Endpoint | SQLite 行為 | Postgres 行為 |
|---|---|---|
| `POST /me/settings/<key>` | 成功,但 FK 對不上 | **500 IntegrityError** |
| `POST /me/sessions` | 成功,但 sessions.user_id 是 username 不是 users.id | **500 IntegrityError** |
| `GET /me/sessions` | 用 username 當 WHERE 查得到(因為 INSERT 時用了 username),功能瞎打瞎中 | 查不到(沒 INSERT 成功)|
| `DELETE /me/sessions/<sid>` | 因為 WHERE user_id=username 對得上 INSERT 用的 username,能刪 | 沒對應 row 可刪,silently no-op |

**Postgres 部署是 production blind spot** — orion 號稱支援(`pyproject.toml` 有 asyncpg 依賴),但實機跑會炸。

## 2. 修法選項

### 選項 A:把 sub 改成 user.id(UUID),所有 callers 用 user.id

- `auth.py:issue_token` 改成:
  ```python
  "sub": str(user.id),
  ```
- `auth_db.py:authenticate` 確保 register / login 時都拿到 user.id
- `current_user` 不變(仍回 sub),但其值現在是 UUID
- DB 寫入路徑全部用 user.id(已是字串型 UUID,跟 schema 對齊)

**✅ 對 schema 友善**:FK 真的指 users.id
**✅ Privacy 升級**:username 不在 token 內(雖然 base64-decoded JWT 還是看得到)
**❌ 既有 token 失效**(payload 變了)— deploy 時要強制 logout 所有 user
**❌ Frontend 顯示 username 要另外 endpoint 拿(`GET /me` 之類)— 多一個 round-trip**

### 選項 B:把 FK 改成參照 `users.username`(加 unique 約束)

- `models.py` 全部 `ForeignKey("users.id")` → `ForeignKey("users.username")`
- `User.username` 已是 `unique=True`,FK 可指
- alembic migration:三張表的 FK 重建

**✅ 既有 token / route 程式碼不動**
**✅ 對 user-visible 沒影響**
**❌ Schema 變醜**:username 是 user 可改的 mutable identifier(若加 rename feature),不該當穩定的 FK target
**❌ Migration 比較重**:三張表的 FK index 都要 rebuild

### 選項 C:混合 — 內部用 user.id,token 仍藏 user.id 但 frontend-friendly endpoint 補 username

跟 A 一樣,但加 `GET /me` 回 `{user_id, username}` 給 frontend 用。其實是 A 的補強版,不是獨立選項。

### 推薦:**A**

- Schema 設計乾淨(FK 永遠指 stable id)
- Token rotation 是合理的安全升級時機(intentional design)
- frontend `/me` endpoint 是小事

## 3. 任務拆解(若做 A)

### 3.1 Auth 層

- [ ] `api/auth.py:issue_token` 改 `"sub": str(user.id)`(login 路徑)
- [ ] `api/auth.py:LoginResponse.user_id` 從 username 改成 user.id(serialized for frontend)
- [ ] `auth_db.py:authenticate` 回 user 物件而非 username 字串
- [ ] Dev fallback(`ORION_AUTH_MODE=dev`)路徑也對齊 — 沒 DB 時生 deterministic UUID(`uuid5(NAMESPACE_DNS, username)`)避免 token 跨重啟失效

### 3.2 Routes

- [ ] `current_user` 不改名,但其值現在是 UUID 字串
- [ ] 所有 routes 不必動(只是字串值意義變了)
- [ ] **新增 `GET /me`**:回 `{user_id: UUID, username: str}`,frontend header 顯示 username 用

### 3.3 Frontend

- [ ] 登入後存 `userId` + `username`(localStorage / context)
- [ ] Header / sidebar 顯示 username 改從 localStorage 拿,不解 JWT
- [ ] 若 frontend 有解 JWT 拿 username 的程式碼 → 改

### 3.4 Migration

- [ ] **Token 失效**:所有 user 強制 re-login。可以走兩條路:
  - (a) 換 JWT signing secret(`ORION_JWT_SECRET`)— 既有 token 全 invalid
  - (b) Token 內加 `version` field,server-side 拒舊版本
- [ ] 既有 DB 資料:`sessions.user_id` 等欄位實際存的是 username。一次性 migrate 改成 user.id:
  ```sql
  UPDATE sessions SET user_id = (SELECT id FROM users WHERE username = sessions.user_id);
  -- 同理對 user_settings / user_preferences
  ```
  alembic migration script 包這幾個 UPDATE。

### 3.5 啟用 PRAGMA + Revert Phase 28 workaround

- [ ] `storage/db/engine.py` 加回 `PRAGMA foreign_keys=ON` listener
- [ ] `DbSessionManager.delete` 可以(但不必)改回依賴 CASCADE。**建議保留手動 DELETE**(跨 DB 一致性更好,顯式 > 隱式)

### 3.6 Tests

- [ ] 既有 user_settings / sessions test 改用 register → 取 user.id 後當 user_id 用
- [ ] 加 test:Postgres-style FK enforcement(用 SQLite + PRAGMA on 模擬),驗 INSERT 對得起來
- [ ] 加 test:token 從舊版(sub=username)送進來 → 401(rotation 保護)

### 3.7 收尾

- [ ] 補測試 + 寫 Phase 29 完工心得
- [ ] 更新 docs:auth flow、PROJECT_LAYOUT、Phase 28 completion 補連結

## 4. 風險

| 風險 | 緩解 |
|---|---|
| Token rotation 強迫所有 user 重登 → 影響 UX | 視為 intentional design change;deploy 時公告;單機 dev 環境無感 |
| Migration script 跑到一半失敗 → 半 migrated state | alembic transactional;失敗回滾;dry-run 模式先驗 |
| Frontend localStorage 內舊 user_id(其實是 username)→ 不一致 | 後端拒舊 token 強迫重登 → frontend 自然重抓 |
| Dev mode(無 DB)不能 register,token sub 該存什麼 | `uuid5(NAMESPACE_DNS, username)` deterministic UUID;不打 DB 也能對齊 |
| Phase 28 的手動 cascade 跟 PRAGMA on 重複 | 不衝突,DELETE 跑兩次第二次 no-op;顯式為主,FK 是安全網 |

## 5. 不該做的

- ❌ **打開 PRAGMA 但不修 auth** — 等於故意把 production 弄壞
- ❌ **改 FK 指 username**(選項 B)— 短期省事但長期 schema 髒
- ❌ **同時搬 user_id schema + 加新 features** — scope 控制,純 refactor

## 6. 相關 code

- `api/auth.py` / `api/auth_db.py` / `api/deps.py` — token 處理
- `api/routes/user_settings.py` / `sessions.py` / `oauth.py` — 拿 current_user 寫 DB
- `storage/db/models.py` — schema(FK 指向)
- `storage/db/engine.py` — Phase 28 註明「不打開 PRAGMA」的位置,Phase 29 反轉
- `storage/db/alembic/versions/` — 加 migration script

## 7. 觸發訊號

什麼時候該做這 phase?

1. **準備 Postgres production 部署** — 不修就直接 500
2. **想啟用 user-level security feature**(rate limit / quota 等需要 stable user_id)
3. **發現新的 user_id 相關 bug**(token 跨機器不一致 / migration 失敗等)

目前(2026-05-12)三條都沒明確,但 **Postgres deploy 一啟動就會踩**,所以前置時程倒推:預計 production deploy 前 1 週做。
