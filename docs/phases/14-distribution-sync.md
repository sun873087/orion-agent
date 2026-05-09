# Phase 14:Distribution & Sync(設定散佈與跨機同步)

## 速覽

- **預計時程**:1-2 週
- **前置 Phase**:Phase 7(production / Postgres)、Phase 13(settings migrations)
- **本文件目的**:解決「使用者換瀏覽器 / 換手機就丟設定」與「OAuth token 明文存 fs 不安全」兩個 production SaaS 痛點
- **主要交付物**:
  - **settingsSync**:跨機器使用者設定同步(client-side 變動 → server-side 同步 → 其他裝置拉)
  - **secureStorage**:OS keychain / 加密 file 儲存 token
  - **dxt**:Anthropic Desktop Extensions plugin 格式(可選)

## ⚠️ Web Chat 場景大幅精簡(REST CRUD 取代 diff sync)

> **TS 原設計**(CLI 多裝置 client-side state):每裝置有本地 `settings.json`,改動 → diff push → server merge → 別裝置 pull diff。需要 conflict 解決(LWW / merge_list / merge_dict)。
>
> **Web chat 改為**:**前端沒有 client-side state**,settings 直接存 Postgres,前端打 REST API 讀寫。**不需要 diff / merge / conflict 那套**。
>
> **本 phase 大幅精簡**:
> - ❌ ~~`SettingsSyncManager.pull / push`~~ → **改成簡單 REST CRUD**(下方 § 5.2)
> - ❌ ~~`SyncCursor`、`SettingDiff`~~ — 不需要
> - ❌ ~~`conflict.py` LWW / merge 邏輯~~ — 同 user 同時開兩個 tab 的 race 用 row version + 樂觀鎖即可
> - ✅ **`secureStorage` 保留**(token 加密用)
> - ✅ **DXT plugin format 保留**(若做 marketplace)
>
> **Phase 14 對 web chat 真正需要的只剩 secureStorage + 簡單 REST settings**。

## 1. 為何需要本 phase?

SaaS 環境下,Phase 7-13 的設定假設**一機一 user**,但現實:

```
User 在桌機改了 model = "opus"
   ↓
Web app(Phase 6)讀的是本機 fs settings.json — 沒桌機那邊
   ↓
User 困惑:「我明明改了啊」

User 用 SSO,Anthropic API token 拿到後存哪?
   ↓
Phase 7 寫 ~/.claude/settings.json(明文)
   ↓
任何能讀該檔的程式都能拿 token
```

**對應 TS 源碼**:
- `src/services/settingsSync/index.ts`(581 行)
- `src/services/settingsSync/types.ts`(67 行)
- `src/utils/secureStorage/`(目錄)
- `src/utils/dxt/`(目錄,DXT plugin format)

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 行數 | 注意 |
|---|---|---|---|
| `src/sync/manager.py` | `src/services/settingsSync/index.ts` | 581 | Sync 主邏輯 |
| `src/sync/types.py` | `src/services/settingsSync/types.ts` | 67 | SyncedSetting 型別 |
| `src/sync/conflict.py` | (散落,自寫)| — | 衝突解決(LWW / merge) |
| `src/storage/secure.py` | `src/utils/secureStorage/`(目錄)| — | OS keychain wrapper |
| `src/plugins/dxt.py` | `src/utils/dxt/`(目錄)| — | DXT format(可選) |

## 3. 任務拆解

### Week 1:settingsSync 主流程

- [ ] 1.1 `sync/types.py`:`SyncedSetting`、`SettingDiff`、`SyncConflict` Pydantic
- [ ] 1.2 `sync/manager.py`:`SettingsSyncManager` 類
- [ ] 1.3 Postgres schema:`user_settings`、`setting_changes`(audit log)
- [ ] 1.4 REST `/sync/settings`(GET pull / PUT push / DELETE clear)
- [ ] 1.5 Conflict 解決(Last-Write-Wins + 標記合併欄位)
- [ ] 1.6 整合到 Phase 13 migrations(同步前先 migrate)
- [ ] 1.7 測試:多裝置並發改、衝突、broken JSON 復原

### Week 2:secureStorage + dxt(輕量)

- [ ] 2.1 `storage/secure.py`:`SecureStorage` 介面
- [ ] 2.2 backend:macOS keychain / Linux keyring / Windows credential manager(用 `keyring` lib)
- [ ] 2.3 fallback:加密 file(`cryptography.fernet` 對稱加密)
- [ ] 2.4 整合到 Phase 5 OAuth token 儲存
- [ ] 2.5 整合到 Phase 7 SaaS 模式(Vault / AWS Secrets Manager)
- [ ] 2.6 `plugins/dxt.py`:DXT zip 載入 + manifest parse(輕量,可選)
- [ ] 2.7 寫 Phase 14 心得

## 4. 模組架構

```
src/claude_agent_py/
├── sync/
│   ├── __init__.py
│   ├── types.py                       # ◀ NEW
│   ├── manager.py                     # ◀ NEW SyncManager
│   └── conflict.py                    # ◀ NEW 衝突解決
│
├── storage/
│   └── secure.py                      # ◀ NEW SecureStorage
│
├── plugins/
│   └── dxt.py                         # ◀ NEW(可選)DXT format

src/api/routes/
└── sync.py                            # ◀ NEW /sync REST endpoints
```

## 5. Python Skeleton

### 5.1 `sync/types.py`

```python
"""Synced setting 型別。對應 TS settingsSync/types.ts。"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel


SyncScope = Literal["user", "device", "session"]
"""user = 跨裝置同步,device = 本裝置 only,session = 跨裝置但僅本 session"""


class SyncedSetting(BaseModel):
    """單一同步設定項。"""
    key: str
    value: Any
    scope: SyncScope = "user"
    updated_at: datetime
    updated_from_device: str
    """裝置 ID(client 自帶,server 紀錄)。"""

    version: int = 1
    """設定 schema version(對應 Phase 13 migration)。"""


class SettingDiff(BaseModel):
    """同步 push 的 diff 格式。"""
    upserts: list[SyncedSetting] = []
    """新增 / 更新。"""

    deletes: list[str] = []
    """要刪的 key list。"""


class SyncConflict(BaseModel):
    """衝突解決紀錄(audit)。"""
    key: str
    local_value: Any
    remote_value: Any
    resolution: Literal["local_wins", "remote_wins", "merged"]
    resolved_at: datetime


class SyncCursor(BaseModel):
    """client 拉 diff 的 cursor。"""
    last_synced_at: datetime
    device_id: str
```

### 5.2(Web Chat 版)— 簡單 REST CRUD

```python
"""Web chat 不需要 diff sync,settings 直接 DB CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from claude_agent_py.api.deps import current_user, get_db
from claude_agent_py.storage.postgres import UserSettingRow


router = APIRouter()


@router.get("/me/settings")
async def get_all_settings(user=Depends(current_user), db=Depends(get_db)):
    """前端拉 user 全部 settings。"""
    rows = (await db.execute(
        select(UserSettingRow).where(
            UserSettingRow.user_id == user.id,
            UserSettingRow.deleted_at.is_(None),
        )
    )).scalars().all()
    return {row.key: row.value for row in rows}


@router.get("/me/settings/{key}")
async def get_setting(key: str, user=Depends(current_user), db=Depends(get_db)):
    row = (await db.execute(
        select(UserSettingRow).where(
            UserSettingRow.user_id == user.id,
            UserSettingRow.key == key,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Setting not found")
    return {"key": row.key, "value": row.value, "version": row.version}


@router.put("/me/settings/{key}")
async def set_setting(
    key: str,
    value: dict,  # {value: ..., version?: int(樂觀鎖)}
    user=Depends(current_user),
    db=Depends(get_db),
):
    """前端打這裡更新。樂觀鎖防多 tab 競爭。"""
    expected_version = value.get("version")
    new_value = value["value"]

    row = (await db.execute(
        select(UserSettingRow).where(
            UserSettingRow.user_id == user.id,
            UserSettingRow.key == key,
        )
    )).scalar_one_or_none()

    if row is None:
        # 新建
        row = UserSettingRow(
            user_id=user.id, key=key, value=new_value, version=1,
        )
        db.add(row)
    else:
        if expected_version is not None and row.version != expected_version:
            raise HTTPException(409, "Version conflict — refresh and retry")
        row.value = new_value
        row.version += 1

    await db.commit()
    return {"key": key, "value": new_value, "version": row.version}


@router.delete("/me/settings/{key}")
async def delete_setting(key: str, user=Depends(current_user), db=Depends(get_db)):
    await db.execute(...)  # mark deleted
    await db.commit()
    return {"deleted": True}
```

**這就是全部**。沒有 diff push、merge、cursor、conflict。前端要改設定 → PUT,要看設定 → GET。多 tab 用樂觀鎖(`version` 欄位)防互相覆蓋。

### 5.2b ~~`sync/manager.py`(CLI 模式 reference,本檔案 web chat 不用)~~

```python
"""SettingsSyncManager — 主同步邏輯。對應 TS services/settingsSync/index.ts。"""
from __future__ import annotations
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from claude_agent_py.sync.types import (
    SyncedSetting, SettingDiff, SyncCursor, SyncConflict,
)
from claude_agent_py.sync.conflict import resolve_conflict
from claude_agent_py.storage.postgres import UserSettingRow


class SettingsSyncManager:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def pull(
        self,
        user_id: str,
        cursor: SyncCursor | None = None,
    ) -> SettingDiff:
        """Client 拉 diff。回傳自 cursor.last_synced_at 後的所有變動。"""
        query = select(UserSettingRow).where(
            UserSettingRow.user_id == user_id,
        )
        if cursor:
            query = query.where(UserSettingRow.updated_at > cursor.last_synced_at)

        rows = (await self.db.execute(query)).scalars().all()
        diff = SettingDiff()
        for row in rows:
            if row.deleted_at is not None:
                diff.deletes.append(row.key)
            else:
                diff.upserts.append(SyncedSetting(
                    key=row.key,
                    value=row.value,
                    scope=row.scope,
                    updated_at=row.updated_at,
                    updated_from_device=row.updated_from_device,
                    version=row.version,
                ))
        return diff

    async def push(
        self,
        user_id: str,
        diff: SettingDiff,
        device_id: str,
    ) -> list[SyncConflict]:
        """Client push 變動到 server。回傳衝突列表(若有)。"""
        conflicts = []

        for setting in diff.upserts:
            existing = await self._get_setting(user_id, setting.key)

            if existing is None:
                # 新增
                await self._upsert(user_id, setting, device_id)
                continue

            if existing.updated_at > setting.updated_at:
                # 衝突:server 端有更新的版本
                resolution = resolve_conflict(
                    local=setting,
                    remote=existing,
                )
                conflicts.append(SyncConflict(
                    key=setting.key,
                    local_value=setting.value,
                    remote_value=existing.value,
                    resolution=resolution["winner"],
                    resolved_at=datetime.utcnow(),
                ))
                # 用 winner 結果
                if resolution["winner"] == "local_wins":
                    await self._upsert(user_id, setting, device_id)
                # remote_wins → 不寫(server 端版本贏)
                continue

            # 沒衝突,正常 upsert
            await self._upsert(user_id, setting, device_id)

        for key in diff.deletes:
            await self._mark_deleted(user_id, key, device_id)

        await self.db.commit()
        return conflicts

    async def _get_setting(self, user_id: str, key: str) -> SyncedSetting | None:
        row = (await self.db.execute(
            select(UserSettingRow).where(
                UserSettingRow.user_id == user_id,
                UserSettingRow.key == key,
                UserSettingRow.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if row is None:
            return None
        return SyncedSetting(
            key=row.key, value=row.value, scope=row.scope,
            updated_at=row.updated_at,
            updated_from_device=row.updated_from_device,
            version=row.version,
        )

    async def _upsert(self, user_id: str, setting: SyncedSetting, device_id: str):
        """Upsert with audit log。"""
        await self.db.execute(
            update(UserSettingRow).where(
                UserSettingRow.user_id == user_id,
                UserSettingRow.key == setting.key,
            ).values(
                value=setting.value,
                scope=setting.scope,
                updated_at=setting.updated_at,
                updated_from_device=device_id,
                version=setting.version,
                deleted_at=None,
            )
        )
        # Audit log
        # ... insert into setting_changes

    async def _mark_deleted(self, user_id: str, key: str, device_id: str):
        await self.db.execute(
            update(UserSettingRow).where(
                UserSettingRow.user_id == user_id,
                UserSettingRow.key == key,
            ).values(
                deleted_at=datetime.utcnow(),
                updated_from_device=device_id,
            )
        )
```

### 5.3 `sync/conflict.py`

```python
"""衝突解決策略。"""
from __future__ import annotations
from typing import Any, Literal

from claude_agent_py.sync.types import SyncedSetting


# 哪些 key 用什麼策略
CONFLICT_STRATEGY = {
    "model": "lww",                    # last-write-wins
    "language": "lww",
    "permissions.rules": "merge_list", # 合併兩邊 list,去重
    "mcpServers": "merge_dict",         # 合併兩邊 dict
    "enabledPlugins": "merge_list",
    # 預設 lww
}


def resolve_conflict(
    *,
    local: SyncedSetting,
    remote: SyncedSetting,
) -> dict:
    """決定誰贏 + 怎麼合併。"""
    strategy = CONFLICT_STRATEGY.get(local.key, "lww")

    if strategy == "lww":
        # last-write-wins
        if local.updated_at >= remote.updated_at:
            return {"winner": "local_wins", "merged_value": local.value}
        return {"winner": "remote_wins", "merged_value": remote.value}

    if strategy == "merge_list":
        # 合併兩邊 list,去重
        local_list = local.value if isinstance(local.value, list) else []
        remote_list = remote.value if isinstance(remote.value, list) else []
        merged = list({*local_list, *remote_list})
        return {"winner": "merged", "merged_value": merged}

    if strategy == "merge_dict":
        local_dict = local.value if isinstance(local.value, dict) else {}
        remote_dict = remote.value if isinstance(remote.value, dict) else {}
        merged = {**remote_dict, **local_dict}
        return {"winner": "merged", "merged_value": merged}

    # fallback
    return {"winner": "local_wins" if local.updated_at >= remote.updated_at else "remote_wins"}
```

### 5.4 `storage/secure.py`

```python
"""SecureStorage — 加密儲存 token。對應 TS utils/secureStorage/。

backend 優先序:
  1. OS keychain(macOS Keychain / Linux Secret Service / Windows Credential Manager)
  2. 加密 file(fallback,用 fernet 對稱加密)
  3. (production)Vault / AWS Secrets Manager / GCP Secret Manager
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Protocol

import keyring  # cross-platform OS keychain
from cryptography.fernet import Fernet


class SecureStorageBackend(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str) -> None: ...
    async def delete(self, key: str) -> None: ...


class KeychainBackend:
    """OS keychain backend(macOS / Linux / Windows)。"""
    SERVICE = "claude-agent-py"

    async def get(self, key: str) -> str | None:
        return keyring.get_password(self.SERVICE, key)

    async def set(self, key: str, value: str) -> None:
        keyring.set_password(self.SERVICE, key, value)

    async def delete(self, key: str) -> None:
        try:
            keyring.delete_password(self.SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass


class EncryptedFileBackend:
    """加密 file backend(fallback / docker container 內無 keychain)。"""

    def __init__(self, file_path: Path, master_key: bytes | None = None):
        self.file_path = file_path
        self.fernet = Fernet(master_key or self._get_or_create_master_key())

    def _get_or_create_master_key(self) -> bytes:
        """取或建主 key。production 應從 env / KMS 取。"""
        key_env = os.environ.get("CLAUDE_AGENT_MASTER_KEY")
        if key_env:
            return key_env.encode()

        key_file = self.file_path.parent / ".master.key"
        if key_file.exists():
            return key_file.read_bytes()

        # Generate new
        new_key = Fernet.generate_key()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(new_key)
        key_file.chmod(0o600)
        return new_key

    async def get(self, key: str) -> str | None:
        if not self.file_path.exists():
            return None
        import json
        data = json.loads(self.file_path.read_text())
        encrypted = data.get(key)
        if encrypted is None:
            return None
        return self.fernet.decrypt(encrypted.encode()).decode()

    async def set(self, key: str, value: str) -> None:
        import json
        data = {}
        if self.file_path.exists():
            data = json.loads(self.file_path.read_text())
        data[key] = self.fernet.encrypt(value.encode()).decode()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps(data))
        self.file_path.chmod(0o600)

    async def delete(self, key: str) -> None:
        if not self.file_path.exists():
            return
        import json
        data = json.loads(self.file_path.read_text())
        data.pop(key, None)
        self.file_path.write_text(json.dumps(data))


class SecretsManagerBackend:
    """AWS Secrets Manager backend(production SaaS)。"""

    def __init__(self, prefix: str = "claude-agent-py/"):
        import aioboto3
        self.session = aioboto3.Session()
        self.prefix = prefix

    async def get(self, key: str) -> str | None:
        async with self.session.client("secretsmanager") as sm:
            try:
                response = await sm.get_secret_value(SecretId=self.prefix + key)
                return response["SecretString"]
            except sm.exceptions.ResourceNotFoundException:
                return None

    async def set(self, key: str, value: str) -> None:
        async with self.session.client("secretsmanager") as sm:
            try:
                await sm.update_secret(SecretId=self.prefix + key, SecretString=value)
            except sm.exceptions.ResourceNotFoundException:
                await sm.create_secret(Name=self.prefix + key, SecretString=value)

    async def delete(self, key: str) -> None:
        async with self.session.client("secretsmanager") as sm:
            try:
                await sm.delete_secret(SecretId=self.prefix + key, ForceDeleteWithoutRecovery=True)
            except sm.exceptions.ResourceNotFoundException:
                pass


def create_backend() -> SecureStorageBackend:
    """根據環境選 backend。"""
    if os.environ.get("CLAUDE_AGENT_USE_AWS_SECRETS") == "1":
        return SecretsManagerBackend()

    if os.environ.get("CLAUDE_AGENT_DISABLE_KEYCHAIN") == "1":
        return EncryptedFileBackend(
            Path("~/.claude_agent_py/secrets.enc").expanduser()
        )

    try:
        # 試 keychain
        kb = KeychainBackend()
        # 簡單 sanity check
        keyring.get_password("test", "test")
        return kb
    except Exception:
        # fallback
        return EncryptedFileBackend(
            Path("~/.claude_agent_py/secrets.enc").expanduser()
        )
```

### 5.5 `plugins/dxt.py`(輕量,可選)

```python
"""DXT(Anthropic Desktop Extensions)plugin format。

DXT 是 zip 格式,內含 manifest + skills + hooks + MCP server。
類似 VS Code .vsix。

Phase 14 簡化版:解 zip → 把內容放到 plugin dir → Phase 8 自動 discover。
"""
from __future__ import annotations
from pathlib import Path
import zipfile
import json


def install_dxt(dxt_path: Path, plugins_dir: Path) -> Path:
    """解開 .dxt 到 plugins_dir/<name>/。"""
    plugins_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(dxt_path, "r") as zf:
        # Manifest 在 root
        manifest_data = json.loads(zf.read("plugin.json"))
        name = manifest_data["name"]

        target = plugins_dir / name
        if target.exists():
            import shutil
            shutil.rmtree(target)

        zf.extractall(target)

    return target


def export_dxt(plugin_dir: Path, output_path: Path) -> None:
    """把 plugin dir 打包成 .dxt。"""
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in plugin_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(plugin_dir))
```

## 6. API 整合

### 6.1 Sync REST endpoints(`api/routes/sync.py`)

```python
from fastapi import APIRouter, Depends
from claude_agent_py.api.deps import current_user, get_db
from claude_agent_py.sync.manager import SettingsSyncManager
from claude_agent_py.sync.types import SettingDiff, SyncCursor


router = APIRouter()


@router.get("/settings")
async def pull_settings(
    cursor_ts: str | None = None,
    device_id: str = "unknown",
    user=Depends(current_user),
    db=Depends(get_db),
):
    """Client 拉 diff。"""
    cursor = None
    if cursor_ts:
        from datetime import datetime
        cursor = SyncCursor(
            last_synced_at=datetime.fromisoformat(cursor_ts),
            device_id=device_id,
        )
    mgr = SettingsSyncManager(db)
    diff = await mgr.pull(user.id, cursor)
    return diff


@router.put("/settings")
async def push_settings(
    diff: SettingDiff,
    device_id: str,
    user=Depends(current_user),
    db=Depends(get_db),
):
    """Client push 變動。"""
    mgr = SettingsSyncManager(db)
    conflicts = await mgr.push(user.id, diff, device_id)
    return {"conflicts": conflicts}
```

### 6.2 Token 儲存改用 SecureStorage

Phase 5 OAuth flow 改造:

```python
# 原 Phase 5 寫到 settings.json:
# settings["mcp_oauth_tokens"][server_name] = token  # ❌ 明文

# Phase 14 改:
from claude_agent_py.storage.secure import create_backend

secure = create_backend()
await secure.set(f"mcp_token:{server_name}", token)  # ✅ 加密
```

## 7. 設計決策

### 為何 Last-Write-Wins 而非 CRDT?

CRDT(conflict-free replicated data type)更精準,但複雜:
- 每個 setting 要 vector clock
- 客戶端要保留歷史
- 程式碼複雜 5-10x

LWW + 對 list / dict 用 merge 已能解 90% 衝突。剩下 10% 在 audit log 裡可手動處理。

對應 TS settingsSync 也是 LWW + 部分 merge。

### 為何 secureStorage 三 backend?

- **本機 dev**:keychain(用 OS 內建,免依賴)
- **Docker / sandbox**:加密 file(沒 OS keychain 可用)
- **production K8s**:AWS Secrets / Vault(集中管理 + audit)

選擇透明(同 `SecureStorageBackend` Protocol),呼叫端不用管。

### 為何 dxt 是輕量?

DXT 只是 zip 格式 + manifest 規範。Phase 8 已有 plugin 系統(從 git URL 安裝),DXT 只是另一種**安裝來源**。實作簡單(zip 解壓 → 套用 Phase 8 plugin loader)。

完整 DXT 規範在 [Anthropic DXT spec](https://www.anthropic.com/) 文件,本 phase 不重複。

### Phase 14 故意不做的

| 項目 | 理由 |
|---|---|
| CRDT 精確衝突解決 | 過度工程,LWW 夠用 |
| 即時 sync(WebSocket push)| 改用 polling + 主動 pull on app focus |
| Settings 加密整體(非 token) | 一般 settings 不敏感,加密 overhead 不值 |
| Multi-user shared settings | scope 外(team feature) |

## 8. 驗收標準

```bash
pytest tests/sync/ tests/storage/test_secure.py -v
```

關鍵測試:

- `test_pull_after_cursor.py` — cursor 後變動正確返
- `test_push_no_conflict.py` — 無衝突 upsert
- `test_push_lww_conflict.py` — server 端較新 → remote_wins
- `test_push_merge_list.py` — `permissions.rules` 兩邊都改 → 合併
- `test_secure_keychain.py` — set / get / delete 正確
- `test_secure_encrypted_file.py` — fallback backend 工作

### 手動驗證

```bash
# 兩個 client(模擬兩裝置)
curl -X PUT /sync/settings -d '{"upserts": [{"key": "model", "value": "opus", ...}]}'

# 另一 client 拉
curl /sync/settings?device_id=mobile

# 應該看到 model = "opus"

# token 存到 keychain
python -c "
import asyncio
from claude_agent_py.storage.secure import create_backend
async def t():
    b = create_backend()
    await b.set('test_token', 'secret123')
    v = await b.get('test_token')
    print(v)
asyncio.run(t())
"
# Output: secret123
# Check: macOS 'Keychain Access' 看到 claude-agent-py 條目
```

## 9. 常見踩雷

### 踩雷 1:Sync clock skew

兩裝置時鐘不一致 → LWW 判斷錯。**用 server 時間**(在 push 時 server 標 updated_at,client 不能寫 updated_at):

```python
# ❌ client 給 timestamp
setting.updated_at = datetime.utcnow()  # client 端

# ✅ server 給 timestamp
@router.put("/settings")
async def push(diff: SettingDiff, ...):
    for s in diff.upserts:
        s.updated_at = datetime.utcnow()  # server 端
```

### 踩雷 2:keychain 跨 user

某些 OS 的 keychain 是 per-user。docker container 內 user 不同 → keychain access fail。**docker 內一律用 EncryptedFileBackend**。

### 踩雷 3:加密 master key 遺失

主 key 寫到 `~/.master.key`,user 換機器忘了帶 → 所有加密的 token 解不開。production:

- 用 KMS / Vault(主 key 在雲端)
- 或讓 user 重新登入(token 重新發)

### 踩雷 4:DXT zip 內含惡意檔

user 安裝第三方 DXT → 可能含惡意 hook / MCP server。要:

- 簽名驗證(future)
- 至少警告 user「即將安裝來自 X 的 plugin」
- 沙盒執行(Phase 7 sandbox 已涵蓋)

### 踩雷 5:Sync 大量衝突 → audit log 爆炸

User 連線時間久 → 大量本地變動 push,衝突 audit log 變大。要:

- audit log 按月 partition
- 過期 cleanup(N 個月)

## 10. 完成清單

- [ ] `SettingsSyncManager` 主邏輯
- [ ] Postgres `user_settings` + `setting_changes` 表
- [ ] REST `/sync/settings` GET / PUT
- [ ] Conflict resolution(LWW + merge_list / merge_dict)
- [ ] `SecureStorage` 介面 + 3 backend
- [ ] OAuth token 改用 SecureStorage
- [ ] DXT zip 安裝 / 匯出(輕量)
- [ ] 寫 Phase 14 心得

完成後進入 [Phase 15:Multi-Agent Patterns](./15-multi-agent.md)。
