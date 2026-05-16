"""Speech-to-text RPCs — OpenAI(Whisper / GPT-4o transcribe family)/ Google Cloud STT。

兩個 provider 一個介面:接 base64 audio + mime + locale → 回 transcript。
OpenAI 有多個 model 可選:
  - whisper-1                 ($0.006/min)— 舊版,通用
  - gpt-4o-mini-transcribe    ($0.003/min)— 比 whisper 便宜、中文準確度更高
  - gpt-4o-transcribe         ($0.006/min)— 最好品質
API keys 從 env 拿:OPENAI_API_KEY / GOOGLE_STT_API_KEY。
"""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from orion_model.stt_catalog import validate_stt
from orion_model.stt_pricing import compute_stt_cost


def _lang_to_whisper(locale: str | None) -> str | None:
    """Whisper 用 ISO-639-1。zh-TW / zh-CN 都 → 'zh'(模型自動辨)。"""
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


def _err(code: str, msg: str) -> dict[str, Any]:
    return {"event": "error", "data": {"code": code, "message": msg}, "final": True}


async def stt_transcribe(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """params:
       provider     : 'openai' | 'google'(舊 'whisper' alias 為 'openai')
       model        : 只 openai 用 — 'whisper-1' | 'gpt-4o-transcribe' |
                      'gpt-4o-mini-transcribe'(預設 whisper-1)
       audio_base64 : str (raw base64,no data: prefix)
       mime_type    : str (e.g. 'audio/webm', 'audio/wav')
       locale       : str (optional;cowork i18n locale)
    回:
       { event: 'transcribed', data: { text, provider, model? }, final: true }
    """
    raw_provider = params.get("provider")
    # 舊版前端傳 'whisper' — 自動 alias 成 openai + whisper-1 model
    if raw_provider == "whisper":
        provider = "openai"
        model = "whisper-1"
    else:
        provider = raw_provider
        model = params.get("model") or "whisper-1"
    audio_b64 = params.get("audio_base64")
    mime = params.get("mime_type") or "audio/webm"
    locale = params.get("locale")
    # 前端錄音時長(估算用 — OpenAI 不在 response 回計費 duration)
    duration_raw = params.get("duration_seconds")
    try:
        duration_seconds = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration_seconds = None
    if provider not in ("openai", "google"):
        yield _err("BAD_PROVIDER", f"unknown provider: {raw_provider!r}")
        return
    # catalog 是 single source of truth(orion-model/stt_models.json),sidecar
    # 不再各自定義白名單 — chat-api / CLI 之後接同一個 catalog 也一致。
    catalog_model = model if provider == "openai" else "default"
    if not validate_stt(provider, catalog_model):
        yield _err("BAD_MODEL", f"unknown {provider} STT model: {catalog_model!r}")
        return
    if not isinstance(audio_b64, str) or not audio_b64:
        yield _err("BAD_AUDIO", "audio_base64 required")
        return
    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
    except (ValueError, TypeError) as e:
        yield _err("BAD_AUDIO", f"base64 decode failed: {e}")
        return
    if len(audio_bytes) < 1024:
        yield _err("EMPTY_AUDIO", "audio too short — try recording for at least a second")
        return

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            yield _err("NO_API_KEY", "OPENAI_API_KEY not set — open Settings and configure it")
            return
        lang = _lang_to_whisper(locale)
        ext = mime.split("/")[-1].split(";")[0] or "webm"
        files = {"file": (f"audio.{ext}", audio_bytes, mime)}
        data: dict[str, str] = {"model": model}
        # gpt-4o-* 也吃 language hint(同 endpoint、同 spec)
        if lang:
            data["language"] = lang
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files,
                    data=data,
                )
                resp.raise_for_status()
                text = resp.json().get("text", "")
        except httpx.HTTPStatusError as e:
            yield _err("API_FAILED", f"OpenAI STT HTTP {e.response.status_code}: {e.response.text[:200]}")
            return
        except httpx.HTTPError as e:
            yield _err("API_FAILED", f"OpenAI STT error: {e}")
            return
        yield {
            "event": "transcribed",
            "data": {
                "text": text,
                "provider": "openai",
                "model": model,
                "duration_seconds": duration_seconds,
                "cost_usd": compute_stt_cost("openai", model, duration_seconds),
            },
            "final": True,
        }
        return

    # provider == "google"
    api_key = os.environ.get("GOOGLE_STT_API_KEY")
    if not api_key:
        yield _err("NO_API_KEY", "GOOGLE_STT_API_KEY not set — see Settings for how to configure")
        return
    encoding = "WEBM_OPUS" if "webm" in mime else "LINEAR16"
    body = {
        "config": {
            "encoding": encoding,
            "languageCode": _lang_to_google(locale),
        },
        "audio": {"content": audio_b64},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://speech.googleapis.com/v1/speech:recognize?key={api_key}",
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
        yield _err("API_FAILED", f"Google STT HTTP {e.response.status_code}: {e.response.text[:200]}")
        return
    except httpx.HTTPError as e:
        yield _err("API_FAILED", f"Google STT error: {e}")
        return
    yield {
        "event": "transcribed",
        "data": {
            "text": text,
            "provider": "google",
            "model": "default",
            "duration_seconds": duration_seconds,
            "cost_usd": compute_stt_cost("google", "default", duration_seconds),
        },
        "final": True,
    }
