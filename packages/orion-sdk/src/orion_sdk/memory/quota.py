"""Memory Layer 4 — per-type soft quota。

Soft quota:**超量不擋寫入**,僅當作 trigger merge-suggest job 的條件。

預設 quota:
- user 50 (個人事實/偏好,通常不會多)
- feedback 100 (規則,累積最快)
- project 30 (per-project;30 條 decision 通常足夠)
- reference 50 (外部資源指向,典型不多)
- (None) 50 (沒分類的)

可用環境變數覆蓋:
    ORION_MEMORY_QUOTA_USER / FEEDBACK / PROJECT / REFERENCE / DEFAULT
"""

from __future__ import annotations

import os
from collections.abc import Iterable

from orion_sdk.memory.types import Memory, MemoryType

_DEFAULT_QUOTAS: dict[MemoryType | None, int] = {
    MemoryType.USER: 50,
    MemoryType.FEEDBACK: 100,
    MemoryType.PROJECT: 30,
    MemoryType.REFERENCE: 50,
    None: 50,
}

_ENV_NAMES: dict[MemoryType | None, str] = {
    MemoryType.USER: "ORION_MEMORY_QUOTA_USER",
    MemoryType.FEEDBACK: "ORION_MEMORY_QUOTA_FEEDBACK",
    MemoryType.PROJECT: "ORION_MEMORY_QUOTA_PROJECT",
    MemoryType.REFERENCE: "ORION_MEMORY_QUOTA_REFERENCE",
    None: "ORION_MEMORY_QUOTA_DEFAULT",
}


def quota_for(mtype: MemoryType | None) -> int:
    """Return effective quota for a memory type,讀 env var 否則 default。

    Bad env value(非整數 / 負數)→ silently fallback default。
    """
    env_name = _ENV_NAMES.get(mtype)
    if env_name:
        raw = os.environ.get(env_name)
        if raw:
            try:
                n = int(raw)
                if n > 0:
                    return n
            except ValueError:
                pass
    return _DEFAULT_QUOTAS[mtype]


def count_by_type(memories: Iterable[Memory]) -> dict[MemoryType | None, int]:
    """數每個 type 多少 memory。"""
    counts: dict[MemoryType | None, int] = {}
    for m in memories:
        counts[m.type] = counts.get(m.type, 0) + 1
    return counts


def over_quota_types(memories: Iterable[Memory]) -> list[tuple[MemoryType | None, int, int]]:
    """Return [(type, current_count, quota)] 為 count > quota 的 type。"""
    counts = count_by_type(memories)
    over: list[tuple[MemoryType | None, int, int]] = []
    for mtype, count in counts.items():
        q = quota_for(mtype)
        if count > q:
            over.append((mtype, count, q))
    return over


def memories_of_type(
    memories: Iterable[Memory], mtype: MemoryType | None
) -> list[Memory]:
    """Filter memories by type(None matches type=None)。"""
    return [m for m in memories if m.type == mtype]
