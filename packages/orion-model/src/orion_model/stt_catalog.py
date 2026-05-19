"""STT (speech-to-text) model catalog — orion-model 對外 API。

跟 catalog.py 一樣的設計,但只給 STT models(per-minute pricing,no token caps)。
單一 source of truth:`stt_models.json`(packaged with package)。Override 在
runtime 透過 `ORION_STT_MODELS_FILE` 環境變數指向外部 JSON。

對外 API:
    list_stt_catalog() -> {"providers": [{ id, label, models: [...] }, ...]}
    validate_stt(provider, model) -> bool
    get_stt_pricing(provider, model) -> float | None    # USD per minute

Consumer(sidecar / chat-api / CLI 等)只應該透過這幾個 entry-point;不要
直接讀 JSON 或重複定義 model list。
"""

from __future__ import annotations

import json
import os
from functools import cache
from importlib import resources
from pathlib import Path
from typing import TypedDict


class SttModelEntry(TypedDict, total=False):
    id: str
    label: str
    pricing_per_minute_usd: float
    recommended: bool
    notes: str


def _override_path() -> Path | None:
    p = os.environ.get("ORION_STT_MODELS_FILE")
    if not p:
        return None
    path = Path(p).expanduser()
    return path if path.is_file() else None


def _parse(
    data: object,
) -> tuple[dict[str, list[SttModelEntry]], dict[str, str]] | None:
    if not isinstance(data, dict):
        return None
    providers = data.get("providers")
    if not isinstance(providers, list):
        return None
    out_models: dict[str, list[SttModelEntry]] = {}
    out_labels: dict[str, str] = {}
    for p in providers:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not pid:
            continue
        out_labels[pid] = str(p.get("label", pid))
        entries: list[SttModelEntry] = []
        raw_models = p.get("models")
        if not isinstance(raw_models, list):
            continue
        for m in raw_models:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            if not isinstance(mid, str) or not mid:
                continue
            entry: SttModelEntry = {
                "id": mid,
                "label": str(m.get("label", mid)),
            }
            pricing = m.get("pricing_per_minute_usd")
            if isinstance(pricing, (int, float)):
                entry["pricing_per_minute_usd"] = float(pricing)
            if m.get("recommended") is True:
                entry["recommended"] = True
            notes = m.get("notes")
            if isinstance(notes, str) and notes:
                entry["notes"] = notes
            entries.append(entry)
        out_models[pid] = entries
    return out_models, out_labels


def _fetch_from_proxy() -> tuple[dict[str, list[SttModelEntry]], dict[str, str]] | None:
    """Phase 31-X — ORION_MODEL_PROXY_URL 設了 → fetch /v1/catalog 拿 stt 段。
    失敗回 None,caller fallback。"""
    proxy = os.environ.get("ORION_MODEL_PROXY_URL")
    if not proxy:
        return None
    try:
        import httpx
        resp = httpx.get(f"{proxy.rstrip('/')}/v1/catalog", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001 - 任何錯都 fallback
        return None
    stt_section = data.get("stt") if isinstance(data, dict) else None
    if not isinstance(stt_section, dict):
        return None
    return _parse(stt_section)


def _read_packaged() -> tuple[dict[str, list[SttModelEntry]], dict[str, str]]:
    data = json.loads(
        resources.files("orion_model").joinpath("stt_models.json").read_text(encoding="utf-8")
    )
    parsed = _parse(data)
    if parsed is None:
        return {}, {}
    return parsed


@cache
def _load() -> tuple[dict[str, list[SttModelEntry]], dict[str, str]]:
    from_proxy = _fetch_from_proxy()
    if from_proxy is not None:
        return from_proxy
    override = _override_path()
    if override is not None:
        try:
            data = json.loads(override.read_text(encoding="utf-8"))
            parsed = _parse(data)
            if parsed is not None:
                return parsed
        except (OSError, json.JSONDecodeError):
            pass
    return _read_packaged()


def _models() -> dict[str, list[SttModelEntry]]:
    return _load()[0]


def _labels() -> dict[str, str]:
    return _load()[1]


def validate_stt(provider: str, model: str) -> bool:
    """Provider × model 是否在 catalog 內。"""
    entries = _models().get(provider) or []
    return any(e["id"] == model for e in entries)


def get_stt_pricing(provider: str, model: str) -> float | None:
    """USD per minute,沒設就回 None。"""
    for e in _models().get(provider) or []:
        if e["id"] == model:
            return e.get("pricing_per_minute_usd")
    return None


def list_stt_catalog() -> dict[str, object]:
    """同 list_catalog():給 RPC / API 顯示用。"""
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
    """Clear @cache so monkeypatched ORION_STT_MODELS_FILE takes effect."""
    _load.cache_clear()


__all__ = [
    "SttModelEntry",
    "get_stt_pricing",
    "list_stt_catalog",
    "reset_cache_for_tests",
    "validate_stt",
]
