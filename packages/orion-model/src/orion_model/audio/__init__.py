"""Audio sub-package — STT / TTS。

跟 chat path(`provider.py`)同 pattern:
- `audio.stt:transcribe()` / `audio.tts:synthesize()` — 純業務邏輯,直連 provider
- `audio:transcribe()` / `audio:synthesize()` facade — env-gate:`ORION_MODEL_PROXY_URL`
  設了走 proxy_client,沒設走直連

Caller(sidecar handlers / proxy server / chat-api 等)只 import facade,拿到結果
不關心後面走哪條路。
"""

from __future__ import annotations

import os

from orion_model.audio.types import SynthesizeResult, TranscribeResult


async def transcribe(
    *,
    provider: str,
    model: str,
    audio_base64: str,
    mime_type: str = "audio/webm",
    locale: str | None = None,
    duration_seconds: float | None = None,
) -> TranscribeResult:
    """STT facade — env-gate proxy / direct。

    Raises:
        ValueError: 參數錯(bad provider / model / audio data)
        RuntimeError: upstream provider 或 proxy HTTP 失敗
    """
    if os.environ.get("ORION_MODEL_PROXY_URL"):
        from orion_model.audio.proxy_client import transcribe_via_proxy
        return await transcribe_via_proxy(
            provider=provider,
            model=model,
            audio_base64=audio_base64,
            mime_type=mime_type,
            locale=locale,
            duration_seconds=duration_seconds,
        )
    from orion_model.audio.stt import transcribe as direct_transcribe
    return await direct_transcribe(
        provider=provider,
        model=model,
        audio_base64=audio_base64,
        mime_type=mime_type,
        locale=locale,
        duration_seconds=duration_seconds,
    )


async def synthesize(
    *,
    provider: str,
    model: str,
    voice: str,
    speed: float,
    text: str,
    audio_format: str = "mp3",
) -> SynthesizeResult:
    """TTS facade。Cache 不在這層 — 上層(sidecar / proxy)自己決定要不要快取。

    Raises:
        ValueError: text 空 / 超 4096 / bad model
        RuntimeError: upstream OpenAI HTTP 失敗
    """
    if os.environ.get("ORION_MODEL_PROXY_URL"):
        from orion_model.audio.proxy_client import synthesize_via_proxy
        return await synthesize_via_proxy(
            provider=provider,
            model=model,
            voice=voice,
            speed=speed,
            text=text,
            audio_format=audio_format,
        )
    from orion_model.audio.tts import synthesize as direct_synthesize
    return await direct_synthesize(
        provider=provider,
        model=model,
        voice=voice,
        speed=speed,
        text=text,
        audio_format=audio_format,
    )


__all__ = [
    "SynthesizeResult",
    "TranscribeResult",
    "synthesize",
    "transcribe",
]
