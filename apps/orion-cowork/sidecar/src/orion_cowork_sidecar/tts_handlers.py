"""Text-to-speech RPCs — OpenAI /audio/speech(目前唯一 cloud provider)。

Web Speech API 走 renderer 直接呼瀏覽器內建 speechSynthesis,**不經 sidecar**。
這檔只處理 cloud TTS。

API key 從 env 拿:OPENAI_API_KEY。沒設就回 error,renderer 收到後自動退回
Web Speech。
"""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from orion_model.tts_catalog import get_tts_pricing, get_tts_voices, validate_tts


def _err(code: str, msg: str) -> dict[str, Any]:
    return {"event": "error", "data": {"code": code, "message": msg}, "final": True}


async def tts_synthesize(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """params:
       provider : 'openai'
       model    : 'tts-1' | 'tts-1-hd'(預設 tts-1)
       voice    : alloy / echo / fable / nova / onyx / shimmer(預設 nova)
       speed    : 0.25 ~ 4.0(預設 1.0)
       text     : 要 synthesize 的文字(已 strip markdown / code blocks)
       format   : 'mp3' | 'opus' | 'aac' | 'flac'(預設 mp3 — renderer Audio 支援度最廣)

    Yields(single frame final):
       { event: 'tts_synthesized', data: { audio_base64, mime_type, provider,
         model, voice, char_count, cost_usd }, final: true }
    """
    provider = params.get("provider")
    model = params.get("model") or "tts-1"
    voice = params.get("voice") or "nova"
    speed_raw = params.get("speed")
    text = params.get("text") or ""
    audio_format = params.get("format") or "mp3"

    if not isinstance(text, str) or not text.strip():
        yield _err("BAD_PARAMS", "text required")
        return
    if not isinstance(provider, str) or provider != "openai":
        yield _err("BAD_PROVIDER", f"only openai supported, got {provider!r}")
        return
    if not validate_tts(provider, model):
        yield _err("BAD_MODEL", f"model {model!r} not in TTS catalog")
        return
    try:
        speed = float(speed_raw) if speed_raw is not None else 1.0
    except (TypeError, ValueError):
        speed = 1.0
    speed = max(0.25, min(4.0, speed))

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        yield _err("NO_API_KEY", "OPENAI_API_KEY not set")
        return

    # OpenAI tts-1 單次 input 上限 4096 chars,超過要 caller 自己切句
    if len(text) > 4096:
        yield _err(
            "TEXT_TOO_LONG",
            f"text length {len(text)} > 4096 chars; caller must chunk",
        )
        return

    mime_map = {
        "mp3": "audio/mpeg",
        "opus": "audio/opus",
        "aac": "audio/aac",
        "flac": "audio/flac",
    }
    mime = mime_map.get(audio_format, "audio/mpeg")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "voice": voice,
                    "input": text,
                    "speed": speed,
                    "response_format": audio_format,
                },
            )
            if resp.status_code != 200:
                yield _err(
                    "OPENAI_ERROR",
                    f"status {resp.status_code}: {resp.text[:200]}",
                )
                return
            audio_bytes = resp.content
    except httpx.HTTPError as e:
        yield _err("HTTP_ERROR", str(e))
        return

    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    char_count = len(text)
    price_per_1m = get_tts_pricing(provider, model) or 0.0
    cost_usd = round(char_count * price_per_1m / 1_000_000, 6)

    yield {
        "event": "tts_synthesized",
        "data": {
            "audio_base64": audio_b64,
            "mime_type": mime,
            "provider": provider,
            "model": model,
            "voice": voice,
            "char_count": char_count,
            "cost_usd": cost_usd,
        },
        "final": True,
    }


async def tts_status(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:  # noqa: ARG001
    """回 TTS 可用狀態 + catalog + 各 provider 是否有 API key。Settings UI 用。"""
    from orion_model.tts_catalog import list_tts_catalog

    catalog = list_tts_catalog()
    providers_meta = []
    for p in catalog.get("providers", []) or []:
        pid = p.get("id") if isinstance(p, dict) else None
        has_key = False
        if pid == "openai":
            has_key = bool(os.environ.get("OPENAI_API_KEY"))
        providers_meta.append({
            "id": pid,
            "label": p.get("label") if isinstance(p, dict) else pid,
            "models": p.get("models") if isinstance(p, dict) else [],
            "voices": p.get("voices") if isinstance(p, dict) else [],
            "api_key_configured": has_key,
        })
    yield {
        "event": "tts_status",
        "data": {"providers": providers_meta},
        "final": True,
    }


__all__ = ["tts_synthesize", "tts_status", "get_tts_voices"]
