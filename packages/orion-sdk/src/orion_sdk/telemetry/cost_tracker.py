"""Per-session cost tracker — Phase 9。對應 TS cost-tracker.ts。

每 session 一個 SessionCostTracker。每次 LLM API call 後 caller 呼 `record(...)`
更新 model 累計。`/sessions/{id}/cost` REST endpoint 回 summary。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from orion_sdk.telemetry.pricing import get_model_pricing


@dataclass
class ModelUsage:
    """單一 model 的累計 usage。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class SessionCostTracker:
    """跨 turn 累計的 session 成本 + token。"""

    session_id: str
    user_id: str | None = None
    by_model: dict[str, ModelUsage] = field(
        default_factory=lambda: defaultdict(ModelUsage),
    )
    total_api_duration_ms: float = 0.0

    def record(
        self,
        *,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        duration_ms: float = 0.0,
    ) -> None:
        m = self.by_model[model]
        m.input_tokens += int(input_tokens)
        m.output_tokens += int(output_tokens)
        m.cache_creation_tokens += int(cache_creation_tokens)
        m.cache_read_tokens += int(cache_read_tokens)
        self.total_api_duration_ms += float(duration_ms)

    def total_cost_usd(self) -> float:
        total = 0.0
        for model, usage in self.by_model.items():
            p = get_model_pricing(model)
            total += (
                usage.input_tokens * p.input_per_token
                + usage.output_tokens * p.output_per_token
                + usage.cache_creation_tokens * p.cache_creation_per_token
                + usage.cache_read_tokens * p.cache_read_per_token
            )
        return total

    def cache_hit_ratio(self) -> float:
        total_input = sum(
            u.input_tokens + u.cache_creation_tokens + u.cache_read_tokens
            for u in self.by_model.values()
        )
        cache_read = sum(u.cache_read_tokens for u in self.by_model.values())
        return cache_read / total_input if total_input > 0 else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "total_cost_usd": round(self.total_cost_usd(), 6),
            "cache_hit_ratio": round(self.cache_hit_ratio(), 4),
            "total_api_duration_ms": round(self.total_api_duration_ms, 2),
            "by_model": {
                model: {
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cache_creation_tokens": u.cache_creation_tokens,
                    "cache_read_tokens": u.cache_read_tokens,
                }
                for model, u in self.by_model.items()
            },
        }


# ─── per-session global registry ─────────────────────────────────────────

_session_trackers: dict[str, SessionCostTracker] = {}


def get_or_create_tracker(
    session_id: str, user_id: str | None = None,
) -> SessionCostTracker:
    """取(沒有就建)該 session 的 tracker。"""
    t = _session_trackers.get(session_id)
    if t is None:
        t = SessionCostTracker(session_id=session_id, user_id=user_id)
        _session_trackers[session_id] = t
    elif user_id is not None and t.user_id is None:
        t.user_id = user_id
    return t


def get_session_summary(session_id: str) -> dict[str, Any] | None:
    """供 /sessions/{id}/cost REST endpoint 用。"""
    t = _session_trackers.get(session_id)
    if t is None:
        return None
    return t.summary()


def reset_trackers() -> None:
    """測試用 — 清空全域 registry。"""
    _session_trackers.clear()
