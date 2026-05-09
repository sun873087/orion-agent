"""Model catalog — UI 可選的 (provider, model) 白名單 + 每 model 的 max_output_tokens。

設計:
- 內建一份 fallback default(對應 pricing.py 已知 keys)。
- 啟動時讀 `api/models.json` 或 `ORION_MODELS_FILE` 指定的檔覆蓋掉 default;
  讀失敗 → 用 default + 記 warning。
- 嚴格驗(unknown pair 拒),避免 client 在 UI 透過 DevTools 塞任意 model。

JSON schema:
{
  "providers": [
    {
      "id": "anthropic",
      "label": "Anthropic",
      "models": [
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6",
         "max_output_tokens": 64000}
      ]
    }
  ]
}
"""

from __future__ import annotations

import json
import logging
import os
from functools import cache
from pathlib import Path
from typing import TypedDict

_log = logging.getLogger(__name__)


class ModelEntry(TypedDict):
    id: str
    label: str
    max_output_tokens: int


# 內建 fallback — JSON 讀不到時使用
_BUILTIN_MODELS: dict[str, list[ModelEntry]] = {
    "anthropic": [
        {"id": "claude-opus-4-7", "label": "Claude Opus 4.7", "max_output_tokens": 32000},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "max_output_tokens": 64000},
        {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "max_output_tokens": 8192},
    ],
    "openai": [
        {"id": "gpt-5.4", "label": "GPT-5.4", "max_output_tokens": 16384},
        {"id": "gpt-5", "label": "GPT-5", "max_output_tokens": 16384},
        {"id": "gpt-5-mini", "label": "GPT-5 mini", "max_output_tokens": 16384},
        {"id": "gpt-4o", "label": "GPT-4o", "max_output_tokens": 16384},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini", "max_output_tokens": 16384},
        {"id": "o3", "label": "o3", "max_output_tokens": 100000},
    ],
}

_BUILTIN_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
}

# default 路徑:repo 根 api/models.json
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "models.json"


def _resolve_config_path() -> Path:
    raw = os.environ.get("ORION_MODELS_FILE")
    if raw:
        return Path(raw).expanduser()
    return _DEFAULT_CONFIG_PATH


def _parse_config(data: object) -> tuple[dict[str, list[ModelEntry]], dict[str, str]] | None:
    """驗 JSON schema → (models_by_provider, provider_labels)。失敗回 None。"""
    if not isinstance(data, dict):
        return None
    providers_raw = data.get("providers")
    if not isinstance(providers_raw, list):
        return None
    models: dict[str, list[ModelEntry]] = {}
    labels: dict[str, str] = {}
    for p in providers_raw:
        if not isinstance(p, dict):
            return None
        pid = p.get("id")
        plabel = p.get("label")
        models_raw = p.get("models")
        if not isinstance(pid, str) or not isinstance(models_raw, list):
            return None
        labels[pid] = plabel if isinstance(plabel, str) else pid
        entries: list[ModelEntry] = []
        for m in models_raw:
            if not isinstance(m, dict):
                return None
            mid = m.get("id")
            mlabel = m.get("label")
            mmax = m.get("max_output_tokens")
            if not isinstance(mid, str):
                return None
            entries.append(
                {
                    "id": mid,
                    "label": mlabel if isinstance(mlabel, str) else mid,
                    "max_output_tokens": mmax if isinstance(mmax, int) and mmax > 0 else 8192,
                }
            )
        models[pid] = entries
    return models, labels


@cache
def _load() -> tuple[dict[str, list[ModelEntry]], dict[str, str]]:
    """讀 JSON config(優先 env path,然後 default 路徑);讀不到 → 用內建。

    cached:server 進程生命週期讀一次。改 JSON 要重啟才生效(跟 .env 一致)。
    """
    path = _resolve_config_path()
    if not path.is_file():
        _log.info("no models config at %s — using built-in defaults", path)
        return dict(_BUILTIN_MODELS), dict(_BUILTIN_PROVIDER_LABELS)
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        _log.warning("failed to load %s (%s) — falling back to built-in", path, e)
        return dict(_BUILTIN_MODELS), dict(_BUILTIN_PROVIDER_LABELS)
    parsed = _parse_config(raw)
    if parsed is None:
        _log.warning("invalid schema in %s — falling back to built-in", path)
        return dict(_BUILTIN_MODELS), dict(_BUILTIN_PROVIDER_LABELS)
    _log.info("loaded models config from %s (%d providers)", path, len(parsed[0]))
    return parsed


def _models() -> dict[str, list[ModelEntry]]:
    return _load()[0]


def _labels() -> dict[str, str]:
    return _load()[1]


def validate(provider: str, model: str) -> bool:
    """嚴格驗 (provider, model) 是否在 catalog 內。不做 prefix fallback。"""
    entries = _models().get(provider)
    if entries is None:
        return False
    return any(e["id"] == model for e in entries)


def get_max_output_tokens(provider: str, model: str) -> int | None:
    """取該 (provider, model) 的 max_output_tokens;未知 → None,caller fallback default。"""
    entries = _models().get(provider)
    if entries is None:
        return None
    for e in entries:
        if e["id"] == model:
            return e["max_output_tokens"]
    return None


def list_catalog() -> dict[str, object]:
    """給 GET /models endpoint 用。caller 自行決定 `available` / `default`。"""
    models = _models()
    labels = _labels()
    return {
        "providers": [
            {
                "id": p,
                "label": labels.get(p, p),
                "models": [dict(e) for e in entries],
            }
            for p, entries in models.items()
        ],
    }


def reset_cache_for_tests() -> None:
    """測試用:讓 monkeypatch 過 ORION_MODELS_FILE 後可重讀。"""
    _load.cache_clear()


__all__ = [
    "ModelEntry",
    "get_max_output_tokens",
    "list_catalog",
    "reset_cache_for_tests",
    "validate",
]
