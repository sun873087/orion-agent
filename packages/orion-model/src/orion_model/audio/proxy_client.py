"""透過 orion-model-proxy 呼 audio endpoints。"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from orion_model.audio.types import SynthesizeResult, TranscribeResult


def _proxy_base_url() -> str:
    url = os.environ.get("ORION_MODEL_PROXY_URL")
    if not url:
        raise RuntimeError("ORION_MODEL_PROXY_URL not set")
    return url.rstrip("/")


def _proxy_headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = os.environ.get("ORION_MODEL_PROXY_KEY")
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


async def transcribe_via_proxy(
    *,
    provider: str,
    model: str,
    audio_base64: str,
    mime_type: str = "audio/webm",
    locale: str | None = None,
    duration_seconds: float | None = None,
) -> TranscribeResult:
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "audio_base64": audio_base64,
        "mime_type": mime_type,
        "locale": locale,
        "duration_seconds": duration_seconds,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_proxy_base_url()}/v1/audio/transcribe",
            json=payload,
            headers=_proxy_headers(),
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"orion-model-proxy STT {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
    return TranscribeResult(
        text=str(data.get("text", "")),
        provider=str(data.get("provider", provider)),
        model=str(data.get("model", model)),
        duration_seconds=data.get("duration_seconds"),
        cost_usd=data.get("cost_usd"),
    )


async def synthesize_via_proxy(
    *,
    provider: str,
    model: str,
    voice: str,
    speed: float,
    text: str,
    audio_format: str = "mp3",
) -> SynthesizeResult:
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "voice": voice,
        "speed": speed,
        "text": text,
        "format": audio_format,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_proxy_base_url()}/v1/audio/speech",
            json=payload,
            headers=_proxy_headers(),
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"orion-model-proxy TTS {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
    audio_b64 = str(data.get("audio_base64", ""))
    audio_bytes = base64.b64decode(audio_b64)
    return SynthesizeResult(
        audio_bytes=audio_bytes,
        mime_type=str(data.get("mime_type", "audio/mpeg")),
        provider=str(data.get("provider", provider)),
        model=str(data.get("model", model)),
        voice=str(data.get("voice", voice)),
        char_count=int(data.get("char_count", len(text))),
        cost_usd=float(data.get("cost_usd", 0.0)),
    )


__all__ = ["synthesize_via_proxy", "transcribe_via_proxy"]
