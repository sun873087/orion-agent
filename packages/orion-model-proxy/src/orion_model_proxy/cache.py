"""Phase 33-E — prompt cache layer。

對 chat/completions、messages、embeddings 等 request body content hash:
    sha256(model + system + messages + temperature)→ key
DB 內 lookup PromptCache 表 → 命中 → 直接回 response_blob,不打 upstream。

只 cache 非 stream non-tool requests(stream / tool-call sequences 重用
不安全)。Phase E 起步用,後續再加 TTL / eviction policy。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from orion_model_proxy.models import PromptCache

_log = logging.getLogger(__name__)


def compute_content_hash(model: str, request_body: bytes) -> str | None:
    """sha256 hash of model + canonicalized body。非 JSON / stream 回 None。"""
    try:
        data = json.loads(request_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # 跳過 stream / tool-call requests(非 deterministic / 多 round)。
    # 用 `key in data` 而非 truthy — `tools=[]` 也算「user 預期可能 tool-use」,
    # 不該命中 cached result。
    if data.get("stream"):
        return None
    if "tools" in data or "tool_choice" in data:
        return None
    # 只 hash 影響 output 的欄
    canonical = {
        "model": model,
        "messages": data.get("messages") or data.get("input"),
        "temperature": data.get("temperature"),
        "max_tokens": data.get("max_tokens") or data.get("max_output_tokens"),
        "system": data.get("system"),
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def lookup(s: AsyncSession, content_hash: str) -> bytes | None:
    """Cache hit → return response_blob and incr hit_count。Miss → None。"""
    row = (
        await s.execute(
            select(PromptCache).where(PromptCache.content_hash == content_hash)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    await s.execute(
        update(PromptCache)
        .where(PromptCache.content_hash == content_hash)
        .values(hit_count=PromptCache.hit_count + 1)
    )
    await s.commit()
    return row.response_blob


async def store(
    s: AsyncSession,
    *,
    content_hash: str,
    provider: str,
    model: str,
    response_blob: bytes,
) -> None:
    """新加 cache entry。重複 hash collide(罕見)直接覆蓋。"""
    existing = (
        await s.execute(
            select(PromptCache).where(PromptCache.content_hash == content_hash)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return  # collision,don't overwrite
    s.add(PromptCache(
        content_hash=content_hash,
        provider=provider,
        model=model,
        response_blob=response_blob,
        created_at=int(time.time()),
        hit_count=0,
    ))
    await s.commit()


__all__ = ["compute_content_hash", "lookup", "store"]
