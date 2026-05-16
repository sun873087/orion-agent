"""STT cost 計算 — thin shim over `stt_catalog.get_stt_pricing`。

跟 `pricing.py` 對齊 chat token pricing 的角色:client 計費都過這層,catalog
沒 pricing 或 (provider, model) 不存在時不 crash,回 None 讓 caller 決定怎麼
顯示(通常就是 "—" / hide)。

對外:
    get_per_minute_price(provider, model) -> float | None    # USD per minute
    compute_stt_cost(provider, model, duration_seconds) -> float | None
"""

from __future__ import annotations

from orion_model.stt_catalog import get_stt_pricing


def get_per_minute_price(provider: str, model: str) -> float | None:
    """USD per minute。Catalog 沒列就回 None(不像 chat pricing 有 fallback —
    STT model 不像 chat 那麼多,沒列就 honest 回 None 讓 UI 顯 'unknown')。"""
    return get_stt_pricing(provider, model)


def compute_stt_cost(
    provider: str, model: str, duration_seconds: float | None
) -> float | None:
    """`duration / 60 × per_minute_usd`,精度 6 位小數。
    duration_seconds None / 非正 / catalog 沒 pricing 都回 None。"""
    if duration_seconds is None or duration_seconds <= 0:
        return None
    per_min = get_per_minute_price(provider, model)
    if per_min is None:
        return None
    return round((duration_seconds / 60.0) * per_min, 6)


__all__ = ["compute_stt_cost", "get_per_minute_price"]
