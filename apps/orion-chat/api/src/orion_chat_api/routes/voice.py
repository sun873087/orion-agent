"""/voice — STT / TTS。

可用性依環境是否設了 voice provider key 判斷。真正的合成 / 轉錄需各 provider SDK
+ per-tenant key 管理(建議走 model-proxy 統一計量,見路線圖的 voice 風險項),
目前未配置時一律回 503;配置與快取 GC 留待後續。
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from orion_chat_api.deps import current_user

router = APIRouter()

# voice provider key(direct mode);proxy mode 由 proxy 端保管
_TTS_KEYS = ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "AZURE_SPEECH_KEY")
_STT_KEYS = ("OPENAI_API_KEY", "DEEPGRAM_API_KEY", "AZURE_SPEECH_KEY")


def _any_key(keys: tuple[str, ...]) -> bool:
    if os.environ.get("ORION_MODEL_PROXY_URL") and os.environ.get(
        "ORION_VOICE_VIA_PROXY",
    ):
        return True
    return any(os.environ.get(k) for k in keys)


class VoiceStatus(BaseModel):
    tts_available: bool
    stt_available: bool


class TtsBody(BaseModel):
    text: str
    # OpenAI TTS 預設(與 cowork 對齊);proxy mode 由 env 切換 base URL
    voice: str = "nova"
    model: str = "tts-1"
    speed: float = 1.0


class TtsResult(BaseModel):
    audio_base64: str
    mime_type: str
    voice: str
    model: str
    cost_usd: float | None = None


class SttBody(BaseModel):
    audio_base64: str
    mime_type: str = "audio/webm"
    # 預設走 OpenAI whisper-1(與 cowork 對齊);proxy mode 由 env 切換 base URL
    provider: str = "openai"
    model: str = "whisper-1"
    locale: str | None = None
    duration_seconds: float | None = None


class SttResult(BaseModel):
    text: str
    provider: str
    model: str
    cost_usd: float | None = None


@router.get("/voice/status", response_model=VoiceStatus)
async def voice_status(
    _user_id: Annotated[str, Depends(current_user)],
) -> VoiceStatus:
    return VoiceStatus(
        tts_available=_any_key(_TTS_KEYS),
        stt_available=_any_key(_STT_KEYS),
    )


@router.post("/voice/tts", response_model=TtsResult)
async def tts(
    body: TtsBody,
    _user_id: Annotated[str, Depends(current_user)],
) -> TtsResult:
    if not _any_key(_TTS_KEYS):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TTS not configured — set a voice provider key (or proxy).",
        )
    if not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty text")

    import base64

    from orion_model.audio import synthesize

    try:
        result = await synthesize(
            provider="openai",
            model=body.model,
            voice=body.voice,
            speed=body.speed,
            text=body.text[:4096],  # OpenAI TTS 上限
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return TtsResult(
        audio_base64=base64.b64encode(result.audio_bytes).decode("ascii"),
        mime_type=result.mime_type,
        voice=result.voice,
        model=result.model,
        cost_usd=result.cost_usd,
    )


@router.post("/voice/stt", response_model=SttResult)
async def stt(
    body: SttBody,
    _user_id: Annotated[str, Depends(current_user)],
) -> SttResult:
    if not _any_key(_STT_KEYS):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STT not configured — set a voice provider key (or proxy).",
        )
    from orion_model.audio import transcribe

    try:
        result = await transcribe(
            provider=body.provider,
            model=body.model,
            audio_base64=body.audio_base64,
            mime_type=body.mime_type,
            locale=body.locale,
            duration_seconds=body.duration_seconds,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except RuntimeError as e:
        # NO_API_KEY / upstream HTTP / proxy 錯 — 屬上游問題
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return SttResult(
        text=result.text,
        provider=result.provider,
        model=result.model,
        cost_usd=result.cost_usd,
    )
