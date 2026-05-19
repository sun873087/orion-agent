"""Audio sub-package — STT / TTS。

跟 chat path 同 pattern:`ORION_MODEL_PROXY_URL` 設了時,內部 httpx call
的 base URL 自動換成 `{proxy}/openai/v1` 或 `{proxy}/anthropic`(transparent
reverse proxy)。host code 不必改。

Direct entry-points:
    audio.stt:transcribe()   — STT
    audio.tts:synthesize()   — TTS
"""

from __future__ import annotations

from orion_model.audio.stt import transcribe
from orion_model.audio.tts import synthesize
from orion_model.audio.types import SynthesizeResult, TranscribeResult

__all__ = [
    "SynthesizeResult",
    "TranscribeResult",
    "synthesize",
    "transcribe",
]
