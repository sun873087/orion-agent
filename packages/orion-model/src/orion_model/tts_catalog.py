"""TTS (text-to-speech) model catalog — parallel STT 設計。

單一 source of truth:`tts_models.json`。Runtime override 透過
`ORION_TTS_MODELS_FILE` 環境變數指外部 JSON。

對外 API:
    list_tts_catalog() -> {"providers": [{ id, label, models, voices }, ...]}
    validate_tts(provider, model) -> bool
    get_tts_pricing(provider, model) -> float | None    # USD per 1M chars
    get_tts_voices(provider) -> list[dict]              # [{ id, label }, ...]

Web Speech API(renderer 內建 speechSynthesis)是免費的 client-side 選項,
**不在 catalog 內** — renderer 直接用,sidecar 不參與。catalog 只列 cloud
provider(目前只有 OpenAI)。
"""

from __future__ import annotations

import json
import os
from functools import cache
from importlib import resources
from pathlib import Path
from typing import TypedDict


class TtsModelEntry(TypedDict, total=False):
    id: str
    label: str
    pricing_per_1m_chars_usd: float
    recommended: bool
    notes: str


class TtsVoiceEntry(TypedDict):
    id: str
    label: str


def _override_path() -> Path | None:
    p = os.environ.get("ORION_TTS_MODELS_FILE")
    if not p:
        return None
    path = Path(p).expanduser()
    return path if path.is_file() else None


def _parse(
    data: object,
) -> tuple[
    dict[str, list[TtsModelEntry]],
    dict[str, list[TtsVoiceEntry]],
    dict[str, str],
] | None:
    if not isinstance(data, dict):
        return None
    providers = data.get("providers")
    if not isinstance(providers, list):
        return None
    out_models: dict[str, list[TtsModelEntry]] = {}
    out_voices: dict[str, list[TtsVoiceEntry]] = {}
    out_labels: dict[str, str] = {}
    for p in providers:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not pid:
            continue
        out_labels[pid] = str(p.get("label", pid))
        entries: list[TtsModelEntry] = []
        for m in p.get("models") or []:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            if not isinstance(mid, str) or not mid:
                continue
            entry: TtsModelEntry = {
                "id": mid,
                "label": str(m.get("label", mid)),
            }
            pricing = m.get("pricing_per_1m_chars_usd")
            if isinstance(pricing, (int, float)):
                entry["pricing_per_1m_chars_usd"] = float(pricing)
            if m.get("recommended") is True:
                entry["recommended"] = True
            notes = m.get("notes")
            if isinstance(notes, str) and notes:
                entry["notes"] = notes
            entries.append(entry)
        out_models[pid] = entries
        voices: list[TtsVoiceEntry] = []
        for v in p.get("voices") or []:
            if not isinstance(v, dict):
                continue
            vid = v.get("id")
            if not isinstance(vid, str) or not vid:
                continue
            voices.append({"id": vid, "label": str(v.get("label", vid))})
        out_voices[pid] = voices
    return out_models, out_voices, out_labels


def _fetch_from_proxy() -> tuple[
    dict[str, list[TtsModelEntry]],
    dict[str, list[TtsVoiceEntry]],
    dict[str, str],
] | None:
    """Phase 31-X — ORION_MODEL_PROXY_URL 設了 → fetch /v1/catalog 拿 tts 段。"""
    proxy = os.environ.get("ORION_MODEL_PROXY_URL")
    if not proxy:
        return None
    try:
        import httpx
        resp = httpx.get(f"{proxy.rstrip('/')}/v1/catalog", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    tts_section = data.get("tts") if isinstance(data, dict) else None
    if not isinstance(tts_section, dict):
        return None
    return _parse(tts_section)


def _read_packaged() -> tuple[
    dict[str, list[TtsModelEntry]],
    dict[str, list[TtsVoiceEntry]],
    dict[str, str],
]:
    data = json.loads(
        resources.files("orion_model").joinpath("tts_models.json").read_text(encoding="utf-8")
    )
    parsed = _parse(data)
    if parsed is None:
        return {}, {}, {}
    return parsed


@cache
def _load() -> tuple[
    dict[str, list[TtsModelEntry]],
    dict[str, list[TtsVoiceEntry]],
    dict[str, str],
]:
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


def validate_tts(provider: str, model: str) -> bool:
    entries = _load()[0].get(provider) or []
    return any(e["id"] == model for e in entries)


def get_tts_pricing(provider: str, model: str) -> float | None:
    """USD per 1M characters,沒設回 None。"""
    for e in _load()[0].get(provider) or []:
        if e["id"] == model:
            return e.get("pricing_per_1m_chars_usd")
    return None


def get_tts_voices(provider: str) -> list[TtsVoiceEntry]:
    return list(_load()[1].get(provider) or [])


def list_tts_catalog() -> dict[str, object]:
    models, voices, labels = _load()
    return {
        "providers": [
            {
                "id": p,
                "label": labels.get(p, p),
                "models": [dict(e) for e in entries],
                "voices": [dict(v) for v in voices.get(p, [])],
            }
            for p, entries in models.items()
        ],
    }


def reset_cache_for_tests() -> None:
    _load.cache_clear()


__all__ = [
    "TtsModelEntry",
    "TtsVoiceEntry",
    "get_tts_pricing",
    "get_tts_voices",
    "list_tts_catalog",
    "reset_cache_for_tests",
    "validate_tts",
]
