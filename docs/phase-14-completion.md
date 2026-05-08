# Phase 14 — Distribution & Sync 完工記錄

**完成日期**:2026-05-08
**Plan doc**:`docs/phases/14-distribution-sync.md`(範圍:Web chat 簡化版 — REST
CRUD 取代 diff sync;`SecureStorage` 兩 backend(Keychain + EncryptedFile);
**spec § 5.5 DXT plugin format 升級為新 phase plan
`docs/phases/22-dxt-plugin-format.md`,本 phase 不做。**
spec § 5.4 SecretsManagerBackend(AWS / Vault)production 雲端 backend 留待
SaaS 真正部署時加,不獨立開 phase plan — 介面 `SecureStorageBackend` Protocol 已就位,
新 backend 直接接即可。)
**狀態**:✅ `make check` 全綠 — **708 unit tests passed, 2 skipped**(20.43s),
ruff clean,mypy --strict 196 files clean。

Phase 13 → Phase 14 新增 **31 unit tests**(secure 19 / user_settings_routes 12 +
1 unauth + 1 no-db = 14)。2 個 skip 是 Phase 7 docker_backend(既有,需 docker daemon)。

---

## 交付清單

### 新增模組

```
src/orion_agent/
├── storage/secure.py                [新] SecureStorageBackend Protocol +
│                                     KeychainBackend + EncryptedFileBackend +
│                                     create_backend factory
├── api/routes/user_settings.py      [新] /me/settings GET all / GET one /
│                                     PUT optimistic / DELETE
└── storage/db/alembic/versions/
    └── 0003_user_settings.py        [新 migration]
```

### 修改既有檔

```
pyproject.toml                       加 cryptography>=42.0 / keyring>=24.0;
                                       mypy override 加 keyring.*

src/orion_agent/
├── api/app.py                       掛 user_settings_router
└── storage/db/models.py             加 UserSetting(user_id+key 複合 PK / value JSON /
                                       version int / updated_at)
```

### Tests(新增 2 檔,共 31 案例)

```
tests/unit/storage/test_secure.py              19 tests
  EncryptedFile(roundtrip / missing / overwrite / delete idempotent /
                list_keys / persists across instances / key change → None /
                env master key / corrupt → empty)
  Keychain     (roundtrip / delete / nonexistent silent / list via index /
                excludes index entry)— 用 fake keyring 不碰真 OS keychain
  Factory      (force_file / disabled env / keychain path / fall back on raise)

tests/unit/api/test_user_settings_routes.py    12 tests
  (get_all_empty / put_creates / get_after_put / get_all_dict / put_increments /
   put_optimistic_conflict / put_without_expected_overwrites /
   get_404 / delete / delete_idempotent / complex_value / unauthorized_no_token)
  + 1 test_no_db_returns_503
```

---

## 設計決策

### 1. Web chat = REST CRUD,不做 diff sync
spec ⚠️ 明確指示:web chat 沒 client-side state,前端打 REST 讀寫。**完全略過**
spec § 5.2b 的 SettingsSyncManager / SyncCursor / SyncConflict / merge_list /
merge_dict — 這些 CLI 多裝置才需要。本 phase 對應 spec § 5.2 的 4 個 endpoint。

### 2. UserSetting 跟 UserPreference 分表
- `UserPreference`(Phase 13)= schema-typed 欄位(custom_instructions / timezone /
  output_style 各自一欄)— 強型別、單 row per user
- `UserSetting`(Phase 14)= 自由 key/value blob、JSON value、複合 PK(user_id+key)
  — 給前端任意設定值用(model 偏好 / UI 偏好 / etc.)

兩者用途不同,**不合併**。

### 3. 樂觀鎖用 `version` 整數欄位,不用 mtime / ETag
- 簡單(SQLite / Postgres 都吃)
- 防多 tab 同 user race(spec § 4 web chat 痛點)
- 前端 GET 拿 version → PUT 帶回 → 不符 409

### 4. PUT 不帶 expected_version 時直接覆蓋(version 仍 +1)
保留 client 「我不在乎覆蓋」的選項;但需要 conflict-aware 的 client 都應該帶
expected_version。

### 5. DELETE idempotent
不存在也回 200(`{deleted: false}`),減少 client 重試邏輯。

### 6. 沒設 `ORION_DB_URL` → 503,不靜默
spec 預設 SaaS production 都會設;dev / test 用 `sqlite+aiosqlite:///:memory:`。
endpoint 顯式 503 比靜默 fallback 到 fs storage 更清楚。

### 7. SecureStorage 兩 backend,優先 keychain
- **Keychain**:`keyring` 套件,跨平台(macOS / Linux Secret Service / Windows
  Credential Manager)。dev 機器最佳體驗(免管 master key)
- **EncryptedFile**:`cryptography.fernet` 對稱加密,master key 從 env
  `ORION_MASTER_KEY` 或 `~/.orion/.master.key`(mode 600)— docker / sandbox / CI 用
- **future SecretsManager**(AWS / Vault)— 同 Protocol 接口,呼叫端不用改

### 8. KeychainBackend 自管 `__index__` 條目
`keyring` 套件本身沒有 list_keys API(各 OS backend 不一致)。實作:每筆 set/delete
也維護一筆 `__index__`(JSON list)在 keychain 裡,`list_keys` 從那讀。
Best-effort,**不保證 audit-grade 一致**(誰直接 OS UI 改 keychain,index 會落後)。

### 9. EncryptedFileBackend 用 atomic save(.tmp + rename)+ chmod 600
- atomic:寫一半 process 死也不會壞 secrets.enc(原檔 intact)
- chmod 600:其他 user 讀不到;Windows 沒此 syscall 用 `contextlib.suppress(OSError)`

### 10. master key 失蹤 → 自動產生,不 raise
首次跑 `EncryptedFileBackend()` 會自動 `Fernet.generate_key()` 寫進
`<file_dir>/.master.key`。後續同一 host 用同 key。**換機器忘了帶 .master.key →
舊資料解不開**(spec § 9 踩雷 #3)— 此時 `get(key)` 回 None(`InvalidToken` 吞),
caller 應重新 set。

### 11. `ORION_MASTER_KEY` env 覆蓋 .master.key 檔
production 走 KMS / Vault 注 env。本機 dev 走 .master.key 檔。順序:env 優先。

### 12. create_backend keychain 失敗 → silent fallback
`get_keyring()` 若 raise(無可用 backend / docker 內 dbus 沒裝)→ logger.info +
回 EncryptedFileBackend。應用層不需處理 backend 切換。

### 13. KeychainBackend `_keyring()` 回 `Any`
`keyring` 套件無 type stub。內部 helper 故意 return `Any`,讓 mypy --strict 不抱怨
`object.set_password` attr。

### 14. Phase 5 OAuth 沒做 → SecureStorage 暫無消費者
`mcp/oauth.py` 是 stub(raise NotImplementedError)。spec § 6.2 要求改用 secure
storage 不適用。**SecureStorage 模組獨立完成**,future OAuth phase 接即可。

---

## REST API 變更

新 endpoints(JWT-protected,需 `ORION_DB_URL` 設定):

```
GET    /me/settings              → dict[key, value](全部)
GET    /me/settings/{key}        → {key, value, version}
PUT    /me/settings/{key}        body: {value: any, expected_version?: int}
                                 → 200 / 409 conflict
DELETE /me/settings/{key}        → {deleted: bool}(idempotent,不存在仍 200)
```

未設 `ORION_DB_URL` → 503 Service Unavailable。

---

## 環境變數

| Env | 用途 |
|---|---|
| `ORION_DB_URL` | user_settings endpoints 必要(沒設則 503),沿用 Phase 13 |
| `ORION_MASTER_KEY` | EncryptedFileBackend 主 key(覆蓋 `.master.key` 檔) |
| `ORION_DISABLE_KEYCHAIN` | `=1` 強制走 EncryptedFileBackend(docker / CI 用) |
| `ORION_KEYCHAIN_SERVICE` | KeychainBackend 的 service name(預設 `orion-agent`) |
| `ORION_HOME` | EncryptedFileBackend 預設 `<ORION_HOME>/secrets.enc` |

---

## DB Schema 變更

Alembic migration `0003_user_settings`:

```sql
CREATE TABLE user_settings (
    user_id    VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key        VARCHAR(128) NOT NULL,
    value      JSON NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, key)
);
CREATE INDEX ix_user_settings_user_id ON user_settings(user_id);
```

dev / 測試走 `init_db()`(create_all)直接建表,跳過 alembic;production 走 alembic upgrade。

---

## 新 Python 依賴

```toml
"cryptography>=42.0",   # Fernet 對稱加密
"keyring>=24.0",        # OS keychain 跨平台 wrapper
```

`cryptography` 是大眾依賴(`bcrypt` 等都隱含 link)。`keyring` 是純 Python wrapper,
OS 端各有 backend(macOS Security framework / Linux dbus secret-service / Windows
Credential Manager)。docker 內可能無 dbus → fallback 走加密檔(已測 cover)。

mypy override 加 `keyring.*`(無 type stub)。

---

## Verification

```bash
cd orion-agent/api/

make check
# → ruff All checks passed!
# → mypy --strict: 196 files, 0 issues
# → pytest: 708 passed, 2 skipped(20.43s)

# user_settings REST 手動驗證
ORION_DB_URL=sqlite+aiosqlite:///tmp/orion-us.db \
  uv run orion serve --port 8768 &
sleep 1
curl -s -X POST http://127.0.0.1:8768/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"passw0rd"}'
TOKEN=$(curl -s -X POST http://127.0.0.1:8768/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"passw0rd"}' | jq -r .token)

# PUT
curl -s -X PUT http://127.0.0.1:8768/me/settings/model \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"value":"claude-opus-4-7"}' | jq
# → {"key":"model","value":"claude-opus-4-7","version":1}

# 樂觀鎖衝突
curl -s -X PUT http://127.0.0.1:8768/me/settings/model \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"value":"claude-haiku-4-5","expected_version":99}' | jq
# → {"detail":"Version conflict for 'model': expected 99, current 1. Refetch and retry."}

# GET all
curl -s http://127.0.0.1:8768/me/settings -H "Authorization: Bearer $TOKEN" | jq
# → {"model":"claude-opus-4-7"}

# SecureStorage(EncryptedFile backend)
ORION_HOME=/tmp/orion-secrets .venv/bin/python -c "
import asyncio
from orion_agent.storage.secure import create_backend

async def main():
    b = create_backend(force_file=True)
    await b.set('mcp_token:github', 'ghp_xxxx')
    print('get:', await b.get('mcp_token:github'))
    print('keys:', await b.list_keys())
    await b.delete('mcp_token:github')
    print('after delete:', await b.get('mcp_token:github'))

asyncio.run(main())
"
# 預期:get: ghp_xxxx / keys: ['mcp_token:github'] / after delete: None
ls -la /tmp/orion-secrets/
# 預期看到 secrets.enc(mode 600)+ .master.key(mode 600)
```

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–13 既有 | 677 | 全綠不動 |
| **Phase 14 secure** | 19 | EncryptedFile + Keychain(fake)+ Factory |
| **Phase 14 user_settings_routes** | 12 | CRUD + 樂觀鎖 + 401 + 503 |
| **總計** | **708 passed / 2 skipped** | mypy --strict 196 files / ruff 全綠 |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| 多 tab 同時改同 setting → 後者覆蓋前者 | 樂觀鎖 `version`;前端 PUT 帶 expected_version → 不符 409 |
| user_settings 寫入失敗破壞既有 row | SQL UPDATE 是 atomic;refresh 後回 client 帶最新 version |
| EncryptedFile master key 遺失 → 解密失敗 | InvalidToken 吞回 None,不 raise(spec § 9 踩雷 #3);production 用 KMS / Vault |
| keychain 在 docker 內無 dbus | `create_backend()` 自動 fallback EncryptedFile;test cover |
| KeychainBackend `__index__` 不一致 | best-effort;不保 audit-grade 一致(spec § 5.4 對應)— 應用層需要時自己掃 |
| 換機器 .master.key 沒帶 → 解不開 | 設計接受該行為;production 走 ORION_MASTER_KEY env(KMS 注) |
| FastAPI HTTPBearer 401/403 不一致 | 401 標準;test 接受兩者(`status_code in (401, 403)`)避免框架版本切換破測試 |
| settings JSON 寫入大小無上限 → DoS | Phase 14 範圍不擋(SQLite TEXT 無上限);production 加 size 檢查留新 phase |
| 沒 `ORION_DB_URL` 但 client 仍打 endpoint | 503 + 明確訊息(`User settings require ORION_DB_URL`)|

---

## 內部對應 spec 的差異

| Spec § | 差異 | 為何 |
|---|---|---|
| 5.1 SyncedSetting / SettingDiff / SyncConflict / SyncCursor | **完全不做** | spec ⚠️ 已標明 web chat 不需要 |
| 5.2 DELETE 用 deleted_at soft delete | 改 hard delete(直接 db.delete) | UserSetting 是 user 自己設定,刪了就刪;audit log 留待新 phase 加 |
| 5.2b SettingsSyncManager pull/push/conflict | **完全不做** | 同上 |
| 5.3 conflict.py LWW / merge_list / merge_dict | **完全不做** | 同上 |
| 5.4 SecretsManagerBackend(AWS) | 不實作,介面就位 | production cloud 部署時直接接 SecureStorageBackend Protocol |
| 5.5 DXT plugin format | **拆出 → `docs/phases/22-dxt-plugin-format.md`** | 主題偏 plugin,不是 sync / secure |
| 6.1 `/sync/settings` GET / PUT(diff) | 改 `/me/settings` REST CRUD | 對應 spec § 5.2 web chat 簡化 |
| 6.2 OAuth token 改 SecureStorage | 介面就位,Phase 5 OAuth 是 stub 沒實際 token 要遷 | 等 OAuth 真做(Phase 5b 或新 phase)再接 |

---

## 實作中發現的坑

### 1. `TestClient(create_app())` 不會自動觸發 lifespan
要 `with TestClient(create_app()) as client:` 才會跑 `_lifespan` 裡的
`db_engine = create_db_engine(...)` + `init_db(...)`。否則 `app.state.db_engine`
是 None,所有 user_settings endpoint 都 503。
既有 `test_sessions.py` 沒 `with` 也能跑因為它走 in-memory SessionManager,
db_engine 不必要。

### 2. DB mode 的 /auth/login 必須先 register
Phase 7 加 DB-backed auth 後,DB mode 的 login 要查 users 表。in-memory SQLite
全空 → login 401 → fixture 拿不到 token。**必先 `POST /auth/register`** 建 user
(密碼 8 chars 以上)。

### 3. FastAPI HTTPBearer 401 vs 403
標準是 401(Unauthorized)。但某些 starlette 版本 / 中介層配置會回 403
(Forbidden)。測試接受兩者(`status_code in (401, 403)`),不綁死框架行為。

### 4. mypy --strict 對 keyring 套件無 type stub
方案二選一:
- pyproject.toml `[[tool.mypy.overrides]] module = ["keyring.*"]
  ignore_missing_imports = true`
- 內部 wrapper return `Any` + isinstance narrow

兩者都做(override 處理 import,wrapper return Any 處理屬性存取)。

### 5. SQLAlchemy 2.0 `Mapped[Any] = mapped_column(JSON)` JSON 欄位
SQLite 把 JSON 存 TEXT,Postgres 用 JSONB。SA 自動翻譯。寫入 dict / list / int 都 OK,
讀回保持 JSON 結構(`{"foo": [1,2]}` 進進出出一致)。

### 6. TestClient `with` block 內各 request 共用同 lifespan
所以 `TestClient(create_app())` 兩次建立會起兩個 in-memory SQLite,各有獨立 user。
fixture 用 `with TestClient(...) as client: ... yield ...` 一個 lifespan 一份 user 即可。

### 7. `_FakeKeyring` mock 不能用 Pydantic BaseModel
KeychainBackend 內部 `kr.set_password(...)` 直接呼方法。MagicMock 也行,但
custom class 比較好控異常邏輯(`delete_password` raise KeyError 模擬不存在)。

### 8. `Annotated[AsyncSession, Depends(_require_db)]` + async generator dependency
`async def _require_db(...) -> AsyncGenerator[AsyncSession, None]: ... yield session`
mypy --strict 要求 return type 顯式 `AsyncGenerator`(不能省)。Phase 13 寫 preferences
時也踩過,本檔沿用同模式。

### 9. value=any 在 PUT body
Pydantic `value: Any` 接任何 JSON。模型驗證會通過 dict / list / int / str / null。
存進 `JSON` 欄位前不需轉換(SA JSON adapter 處理)。
