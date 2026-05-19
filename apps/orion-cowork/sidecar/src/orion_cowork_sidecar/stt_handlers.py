"""Speech-to-text RPCs — thin wrapper(Phase 31-X 後)。

業務邏輯搬到 `orion_model.audio.transcribe()`(env-gate proxy / direct)。
這檔只負責:
  1. RPC params 解析 + 'whisper' legacy alias
  2. 包裝成 sidecar RPC frame(`event: transcribed` / `event: error`)

幾個 host(cowork / chat-api / cli)都能透過 orion_model.audio 共用同條 path。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from orion_model.audio import transcribe


def _err(code: str, msg: str) -> dict[str, Any]:
    return {"event": "error", "data": {"code": code, "message": msg}, "final": True}


async def stt_transcribe(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """params:
       provider     : 'openai' | 'google'(舊 'whisper' alias 為 'openai')
       model        : openai 才用('whisper-1' | 'gpt-4o-transcribe' |
                       'gpt-4o-mini-transcribe',預設 whisper-1)
       audio_base64 : str (raw base64,no data: prefix)
       mime_type    : str (e.g. 'audio/webm', 'audio/wav')
       locale       : str (optional;cowork i18n locale)
       duration_seconds : float (前端估算)— OpenAI response 不含 duration
    回:
       { event: 'transcribed', data: {...}, final: true }
       Phase 31-X:ORION_MODEL_PROXY_URL 有設 → 走 proxy `/v1/audio/transcribe`,
                  沒設 → 直連 OpenAI / Google
    """
    raw_provider = params.get("provider")
    # 舊版前端傳 'whisper' — 自動 alias 成 openai + whisper-1
    if raw_provider == "whisper":
        provider = "openai"
        model = "whisper-1"
    else:
        provider = raw_provider if isinstance(raw_provider, str) else ""
        model = params.get("model") or "whisper-1"
    audio_b64 = params.get("audio_base64") or ""
    mime = params.get("mime_type") or "audio/webm"
    locale = params.get("locale")
    duration_raw = params.get("duration_seconds")
    try:
        duration_seconds = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration_seconds = None

    try:
        result = await transcribe(
            provider=provider,
            model=model,
            audio_base64=audio_b64,
            mime_type=mime,
            locale=locale,
            duration_seconds=duration_seconds,
        )
    except ValueError as e:
        yield _err("BAD_PARAMS", str(e))
        return
    except RuntimeError as e:
        # 包含 NO_API_KEY / upstream HTTP / proxy 錯
        yield _err("API_FAILED", str(e))
        return

    yield {
        "event": "transcribed",
        "data": {
            "text": result.text,
            "provider": result.provider,
            "model": result.model,
            "duration_seconds": result.duration_seconds,
            "cost_usd": result.cost_usd,
        },
        "final": True,
    }
