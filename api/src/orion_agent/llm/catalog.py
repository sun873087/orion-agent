"""Model catalog — UI 可選的 (provider, model) 白名單。

跟 `pricing.py` 分開:pricing 為估價用,有 prefix fallback;catalog 是嚴格驗證,
unknown pair 直接拒,避免使用者在 UI 透過 DevTools 塞任意 model 字串給 backend。
"""

from __future__ import annotations

from typing import TypedDict


class ModelEntry(TypedDict):
    id: str
    label: str


# (provider, ordered models) — list 順序 = UI 顯示順序
MODELS: dict[str, list[ModelEntry]] = {
    "anthropic": [
        {"id": "claude-opus-4-7", "label": "Claude Opus 4.7"},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
        {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
    ],
    "openai": [
        {"id": "gpt-5.4", "label": "GPT-5.4"},
        {"id": "gpt-5", "label": "GPT-5"},
        {"id": "gpt-5-mini", "label": "GPT-5 mini"},
        {"id": "gpt-4o", "label": "GPT-4o"},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
        {"id": "o3", "label": "o3"},
    ],
}


PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
}


def validate(provider: str, model: str) -> bool:
    """嚴格驗 (provider, model) 是否在 catalog 內。不做 prefix fallback。"""
    entries = MODELS.get(provider)
    if entries is None:
        return False
    return any(e["id"] == model for e in entries)


def list_catalog() -> dict[str, object]:
    """給 GET /models endpoint 用。caller 自行決定 `available` / `default`。"""
    return {
        "providers": [
            {
                "id": p,
                "label": PROVIDER_LABELS[p],
                "models": list(entries),
            }
            for p, entries in MODELS.items()
        ],
    }


__all__ = ["MODELS", "PROVIDER_LABELS", "ModelEntry", "list_catalog", "validate"]
