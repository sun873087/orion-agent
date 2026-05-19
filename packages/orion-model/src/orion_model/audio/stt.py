"""STT direct provider 呼叫。從 sidecar.stt_handlers 抽出來純業務邏輯。

跟 stt_handlers 的差別:
- 不 yield RPC frame,純 async function → 回 TranscribeResult / 拋例外
- 不依 cowork sidecar 任何東西,任何 host(chat-api / cowork / cli / proxy)都能用
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from orion_model.audio.types import TranscribeResult
from orion_model.stt_catalog import validate_stt
from orion_model.stt_pricing import compute_stt_cost


def _openai_base() -> str:
    """OpenAI base URL — env ORION_MODEL_PROXY_URL 有設改 {proxy}/openai。"""
    proxy = os.environ.get("ORION_MODEL_PROXY_URL")
    if proxy:
        return f"{proxy.rstrip('/')}/openai"
    return "https://api.openai.com"


def _google_base() -> str:
    """Google STT 沒走 proxy(目前沒做 google passthrough);維持直連。"""
    return "https://speech.googleapis.com"


def _lang_to_whisper(locale: str | None) -> str | None:
    """Whisper 用 ISO-639-1。zh-TW / zh-CN 都 → 'zh'。"""
    if not locale:
        return None
    lower = locale.lower()
    if lower.startswith("zh"):
        return "zh"
    if lower.startswith("ja"):
        return "ja"
    if lower.startswith("en"):
        return "en"
    return None


def _lang_to_google(locale: str | None) -> str:
    """Google Cloud STT 用 BCP-47。"""
    if locale == "zh-TW":
        return "cmn-Hant-TW"
    if locale == "zh-CN":
        return "cmn-Hans-CN"
    if locale == "ja":
        return "ja-JP"
    return "en-US"


async def transcribe(
    *,
    provider: str,
    model: str,
    audio_base64: str,
    mime_type: str = "audio/webm",
    locale: str | None = None,
    duration_seconds: float | None = None,
) -> TranscribeResult:
    """直連 OpenAI / Google STT。caller 端統一介面;不關心後面走哪條路。

    Raises:
        ValueError: provider / model / audio_base64 不合法
        RuntimeError: upstream HTTP 失敗 / no api key
    """
    if provider not in ("openai", "google"):
        raise ValueError(f"unknown STT provider: {provider!r}")
    catalog_model = model if provider == "openai" else "default"
    if not validate_stt(provider, catalog_model):
        raise ValueError(f"unknown {provider} STT model: {catalog_model!r}")
    if not isinstance(audio_base64, str) or not audio_base64:
        raise ValueError("audio_base64 required")
    try:
        audio_bytes = base64.b64decode(audio_base64, validate=True)
    except (ValueError, TypeError) as e:
        raise ValueError(f"base64 decode failed: {e}") from e
    if len(audio_bytes) < 1024:
        raise ValueError("audio too short — at least 1 second")

    if provider == "openai":
        use_proxy = bool(os.environ.get("ORION_MODEL_PROXY_URL"))
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            if use_proxy:
                api_key = "via-proxy"
            else:
                raise RuntimeError("OPENAI_API_KEY not set")
        lang = _lang_to_whisper(locale)
        ext = mime_type.split("/")[-1].split(";")[0] or "webm"
        files = {"file": (f"audio.{ext}", audio_bytes, mime_type)}
        data: dict[str, Any] = {"model": model}
        if lang:
            data["language"] = lang
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{_openai_base()}/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files,
                    data=data,
                )
                resp.raise_for_status()
                text = resp.json().get("text", "")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"OpenAI STT HTTP {e.response.status_code}: {e.response.text[:200]}"
            ) from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"OpenAI STT error: {e}") from e
        return TranscribeResult(
            text=text,
            provider="openai",
            model=model,
            duration_seconds=duration_seconds,
            cost_usd=compute_stt_cost("openai", model, duration_seconds),
        )

    # provider == "google"
    api_key = os.environ.get("GOOGLE_STT_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_STT_API_KEY not set")
    encoding = "WEBM_OPUS" if "webm" in mime_type else "LINEAR16"
    body = {
        "config": {
            "encoding": encoding,
            "languageCode": _lang_to_google(locale),
        },
        "audio": {"content": audio_base64},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{_google_base()}/v1/speech:recognize?key={api_key}",
                json=body,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
            parts: list[str] = []
            for r in results:
                alts = r.get("alternatives") or []
                if alts and alts[0].get("transcript"):
                    parts.append(alts[0]["transcript"])
            text = " ".join(parts).strip()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Google STT HTTP {e.response.status_code}: {e.response.text[:200]}"
        ) from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"Google STT error: {e}") from e
    return TranscribeResult(
        text=text,
        provider="google",
        model="default",
        duration_seconds=duration_seconds,
        cost_usd=compute_stt_cost("google", "default", duration_seconds),
    )


__all__ = ["transcribe"]
