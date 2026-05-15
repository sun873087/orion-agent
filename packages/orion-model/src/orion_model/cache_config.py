"""Cache TTL 設定 — 讀 env vars。

對應 4 個 cache breakpoint 各自的 TTL:
- static system block(`ORION_CACHE_TTL_STATIC`,預設 1h)
- session-stable system block(`ORION_CACHE_TTL_SESSION`,預設 1h)
- messages 全部 bp(`ORION_CACHE_TTL_MESSAGES`,預設 5m)

Anthropic 支援值:`5m`(預設,1.25× 寫入)、`1h`(2× 寫入)。讀取永遠 0.1×。

選 1h vs 5m 的考量:
- 跨 5 分鐘以上仍重用 → 1h 更划算(寫入多 0.75×,但避免重 cache write)
- static / session-stable 通常跨多 turn / 跨閒置時間,1h 較划算
- messages 每 turn 都更新,5m 夠用
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

ValidTTL = Literal["5m", "1h"]


_VALID_TTLS = ("5m", "1h")


@dataclass(frozen=True)
class CacheTTLConfig:
    """每層 cache 的 TTL 設定。"""

    static: ValidTTL = "1h"
    """system block 0(7 段靜態 prompt)— 跨 session 不變,1h 最划算。"""

    session: ValidTTL = "1h"
    """system block 1(session-stable 動態段)— 對話跨閒置仍重用,1h 較佳。"""

    messages: ValidTTL = "5m"
    """messages 各 bp — 每 turn 都更新,5m 夠用,寫入便宜。"""


def _parse_ttl(raw: str | None, default: ValidTTL) -> ValidTTL:
    """env 讀進來的 TTL 字串 → ValidTTL,無效值 fallback 到 default。"""
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in _VALID_TTLS:
        return raw  # type: ignore[return-value]
    return default


def load_cache_ttl_config() -> CacheTTLConfig:
    """從 env 讀 TTL 設定,無效值靜默 fallback 到預設。"""
    return CacheTTLConfig(
        static=_parse_ttl(os.environ.get("ORION_CACHE_TTL_STATIC"), "1h"),
        session=_parse_ttl(os.environ.get("ORION_CACHE_TTL_SESSION"), "1h"),
        messages=_parse_ttl(os.environ.get("ORION_CACHE_TTL_MESSAGES"), "5m"),
    )


def build_cache_control(ttl: ValidTTL) -> dict[str, Any]:
    """產 cache_control dict。`5m` → {"type": "ephemeral"},`1h` 多帶 ttl 欄位。"""
    cc: dict[str, Any] = {"type": "ephemeral"}
    if ttl == "1h":
        cc["ttl"] = "1h"
    return cc
