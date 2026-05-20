"""Proxy DB backup / restore — dump 全表進 JSON,壓 zip。

跨 SQLite ↔ Postgres:不用 sqlite-specific dump,而是 ORM select all rows
→ json.dump → zip。Restore 反向。Schema 兼容 = users / api_keys /
usage_log / audit_log / webhooks / routing_aliases / prompt_cache /
organizations / usage_monthly。

Schema version 寫進 manifest.json,restore 時 check。
"""

from __future__ import annotations

import asyncio
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.models import (
    ApiKey,
    AuditLog,
    Organization,
    PromptCache,
    RoutingAlias,
    UsageLog,
    UsageMonthlyRollup,
    User,
    Webhook,
)


_SCHEMA_VERSION = 1
_MANIFEST_NAME = "manifest.json"


# (model_class, json_filename)— 順序很重要:User 在 ApiKey 前(FK 約束)
_TABLES: list[tuple[type, str]] = [
    (Organization, "organizations.json"),
    (User, "users.json"),
    (ApiKey, "api_keys.json"),
    (UsageLog, "usage_log.json"),
    (UsageMonthlyRollup, "usage_monthly.json"),
    (AuditLog, "audit_log.json"),
    (Webhook, "webhooks.json"),
    (RoutingAlias, "routing_aliases.json"),
    (PromptCache, "prompt_cache.json"),
]


def _to_dict(row: Any) -> dict[str, Any]:
    """ORM row → plain dict(只取 column,不取 relationship)。"""
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        # bytes(PromptCache.response_blob)→ base64 string
        if isinstance(v, bytes):
            import base64
            v = "b64:" + base64.b64encode(v).decode("ascii")
        out[col.name] = v
    return out


def _from_dict(model_cls: type, data: dict[str, Any]) -> Any:
    """Plain dict → ORM row(反向)。"""
    import base64
    fixed: dict[str, Any] = {}
    for col in model_cls.__table__.columns:
        if col.name not in data:
            continue
        v = data[col.name]
        if isinstance(v, str) and v.startswith("b64:"):
            v = base64.b64decode(v[4:])
        fixed[col.name] = v
    return model_cls(**fixed)


@dataclass
class BackupStats:
    path: str
    schema_version: int
    table_counts: dict[str, int]
    exported_at: int


async def backup_to_zip(s: AsyncSession, target_path: Path) -> BackupStats:
    """Dump 全表 → zip。寫進 `target_path`(caller 提供絕對路徑)。"""
    table_counts: dict[str, int] = {}
    dumps: dict[str, str] = {}
    for cls, fname in _TABLES:
        rows = (await s.execute(select(cls))).scalars().all()
        dumps[fname] = json.dumps([_to_dict(r) for r in rows], ensure_ascii=False, indent=2)
        table_counts[cls.__tablename__] = len(rows)

    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "exported_at": int(time.time()),
        "table_counts": table_counts,
    }

    def _write() -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_MANIFEST_NAME, json.dumps(manifest, indent=2))
            for fname, content in dumps.items():
                zf.writestr(fname, content)

    await asyncio.to_thread(_write)
    return BackupStats(
        path=str(target_path),
        schema_version=_SCHEMA_VERSION,
        table_counts=table_counts,
        exported_at=manifest["exported_at"],
    )


@dataclass
class RestoreStats:
    schema_version: int
    table_counts: dict[str, int]


async def restore_from_zip(
    s: AsyncSession, source_path: Path, *, replace_all: bool = True
) -> RestoreStats:
    """從 zip 還原。replace_all=True 會先 truncate 所有表(預設,避免雙倍 row);
    False = merge 模式(可能 PK collision,謹慎用)。"""

    def _read() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
        with zipfile.ZipFile(source_path, "r") as zf:
            if _MANIFEST_NAME not in zf.namelist():
                raise ValueError("missing manifest.json — not an orion proxy backup")
            with zf.open(_MANIFEST_NAME) as fh:
                m = json.load(fh)
            tables_data: dict[str, list[dict[str, Any]]] = {}
            for cls, fname in _TABLES:
                if fname in zf.namelist():
                    with zf.open(fname) as fh:
                        tables_data[cls.__tablename__] = json.load(fh)
                else:
                    tables_data[cls.__tablename__] = []
        return m, tables_data

    manifest, tables_data = await asyncio.to_thread(_read)
    if manifest.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(
            f"schema {manifest.get('schema_version')!r} != expected {_SCHEMA_VERSION}"
        )

    if replace_all:
        # 反向順序(FK 依賴)— 先刪 child 再刪 parent
        for cls, _ in reversed(_TABLES):
            await s.execute(delete(cls))

    counts: dict[str, int] = {}
    for cls, _ in _TABLES:
        rows = tables_data.get(cls.__tablename__, [])
        for row_data in rows:
            s.add(_from_dict(cls, row_data))
        counts[cls.__tablename__] = len(rows)
    await s.commit()

    return RestoreStats(
        schema_version=manifest["schema_version"],
        table_counts=counts,
    )


__all__ = ["BackupStats", "RestoreStats", "backup_to_zip", "restore_from_zip"]
