"""Section cache — module-level dict 存靜態段計算結果。

對應 spec § 5.1 sections.py。

設計:
- 第一次 call → 計算 + 存 cache
- 第二次同 key → 直接從 cache 取
- DANGEROUS_uncached=True 繞過(測試 / 強制重算)
- clear_section_cache() 全清(測試 / `/clear` command 用)

cache key 包含足夠 context 區分(例:user_id 或 cwd 雜湊),避免不同 user 共用。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

_section_cache: dict[str, object] = {}
"""key → cached value。Module-level,跨 conversation 共享。"""


DANGEROUS_uncached = "DANGEROUS_uncached"
"""sentinel string;若 caller 傳此值當 cache_key,**不**走 cache。"""


def section_cache_size() -> int:
    """目前 cache 內幾個 entry。給測試 / debug 用。"""
    return len(_section_cache)


def clear_section_cache() -> None:
    """清空 cache。測試 isolation + `/clear` 用。"""
    _section_cache.clear()


async def register_section(
    cache_key: str,
    builder: Callable[[], Awaitable[T]],
) -> T:
    """取得 section value(從 cache 或現算)。

    Args:
        cache_key: 唯一 key;若 == DANGEROUS_uncached 則不走 cache
        builder: async function,首次 call 時用以計算 value

    Returns:
        builder() 的結果(現算或 cached)
    """
    if cache_key == DANGEROUS_uncached:
        return await builder()

    if cache_key in _section_cache:
        return _section_cache[cache_key]  # type: ignore[return-value]

    value = await builder()
    _section_cache[cache_key] = value
    return value
