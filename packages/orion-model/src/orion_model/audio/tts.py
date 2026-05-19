"""TTS direct provider 呼叫。從 sidecar.tts_handlers 抽出來純業務邏輯,
不含 cache(cache 留 sidecar 端,跟 ~/.orion/tts-cache 對齊)。"""

from __future__ import annotations

import os

import httpx

from orion_model.audio.types import SynthesizeResult
from orion_model.tts_catalog import get_tts_pricing, validate_tts


_MIME_MAP = {
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "flac": "audio/flac",
}


def _openai_base() -> str:
    proxy = os.environ.get("ORION_MODEL_PROXY_URL")
    if proxy:
        return f"{proxy.rstrip('/')}/openai"
    return "https://api.openai.com"


async def synthesize(
    *,
    provider: str,
    model: str,
    voice: str,
    speed: float,
    text: str,
    audio_format: str = "mp3",
) -> SynthesizeResult:
    """直連 OpenAI /audio/speech。

    Raises:
        ValueError: text 空 / 超 4096 / bad model
        RuntimeError: OPENAI_API_KEY 未設 / upstream HTTP 失敗
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text required")
    if provider != "openai":
        raise ValueError(f"only openai TTS supported, got {provider!r}")
    if not validate_tts(provider, model):
        raise ValueError(f"unknown TTS model: {model!r}")
    if len(text) > 4096:
        raise ValueError(f"text length {len(text)} > 4096 chars; caller must chunk")
    speed = max(0.25, min(4.0, float(speed)))

    # 走 proxy 時 Bearer 用 PROXY_KEY(若 proxy 有開 auth);proxy reverse
    # 那層覆寫成真實 OPENAI_API_KEY 才 forward。直連時必須有 OPENAI_API_KEY。
    use_proxy = bool(os.environ.get("ORION_MODEL_PROXY_URL"))
    if use_proxy:
        bearer = os.environ.get("ORION_MODEL_PROXY_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        ) or "via-proxy"
    else:
        bearer = os.environ.get("OPENAI_API_KEY")
        if not bearer:
            raise RuntimeError("OPENAI_API_KEY not set")

    mime = _MIME_MAP.get(audio_format, "audio/mpeg")
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{_openai_base()}/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {bearer}",
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
                raise RuntimeError(
                    f"OpenAI TTS HTTP {resp.status_code}: {resp.text[:200]}"
                )
            audio_bytes = resp.content
    except httpx.HTTPError as e:
        raise RuntimeError(f"OpenAI TTS error: {e}") from e

    char_count = len(text)
    price_per_1m = get_tts_pricing(provider, model) or 0.0
    cost_usd = round(char_count * price_per_1m / 1_000_000, 6)
    return SynthesizeResult(
        audio_bytes=audio_bytes,
        mime_type=mime,
        provider=provider,
        model=model,
        voice=voice,
        char_count=char_count,
        cost_usd=cost_usd,
    )


__all__ = ["synthesize"]
