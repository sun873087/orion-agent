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
    voice: str | None = None


@router.get("/voice/status", response_model=VoiceStatus)
async def voice_status(
    _user_id: Annotated[str, Depends(current_user)],
) -> VoiceStatus:
    return VoiceStatus(
        tts_available=_any_key(_TTS_KEYS),
        stt_available=_any_key(_STT_KEYS),
    )


@router.post("/voice/tts")
async def tts(
    _body: TtsBody,
    _user_id: Annotated[str, Depends(current_user)],
) -> dict[str, str]:
    if not _any_key(_TTS_KEYS):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TTS not configured — set a voice provider key (or proxy).",
        )
    # 實際合成(provider SDK + per-user cache GC)留待後續整合
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "TTS synthesis integration is a follow-up.",
    )


@router.post("/voice/stt")
async def stt(
    _user_id: Annotated[str, Depends(current_user)],
) -> dict[str, str]:
    if not _any_key(_STT_KEYS):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "STT not configured — set a voice provider key (or proxy).",
        )
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "STT transcription integration is a follow-up.",
    )
