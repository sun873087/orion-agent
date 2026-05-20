"""Text-to-speech RPCs — OpenAI /audio/speech(目前唯一 cloud provider)。

Web Speech API 走 renderer 直接呼瀏覽器內建 speechSynthesis,**不經 sidecar**。
這檔只處理 cloud TTS。

API key 從 env 拿:OPENAI_API_KEY。沒設就回 error,renderer 收到後自動退回
Web Speech。
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from orion_model.audio import synthesize as audio_synthesize
from orion_model.tts_catalog import get_tts_pricing, get_tts_voices, validate_tts


def _err(code: str, msg: str) -> dict[str, Any]:
    return {"event": "error", "data": {"code": code, "message": msg}, "final": True}


def _tts_cache_dir() -> Path:
    """Cache 落 ~/.orion/tts-cache/(跟 plans / blobs 同層)。可由 storage.data_dir 覆寫。"""
    # 避免循環 import:直接 expand HOME + ORION_COWORK_DATA_DIR
    root_override = os.environ.get("ORION_COWORK_DATA_DIR")
    root = Path(root_override) if root_override else Path.home() / ".orion"
    return root / "tts-cache"


def _cache_key(*, text: str, model: str, voice: str, speed: float, audio_format: str) -> str:
    """穩定 hash:同樣 (text, model, voice, speed, format) → 同樣 key。speed 取小數
    後 2 位避免浮點誤差讓 cache miss(1.0 vs 1.00 是同一個 key)。"""
    norm_speed = f"{speed:.2f}"
    raw = f"{model}|{voice}|{norm_speed}|{audio_format}|{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def cleanup_old_tts_cache(*, days: int = 30) -> dict[str, int]:
    """掃 cache 目錄,mtime > N 天的 unlink。同 plan files GC pattern。
    Sidecar 啟動 fire-and-forget 跑一次。idempotent。"""
    cache_dir = _tts_cache_dir()
    if not cache_dir.exists():
        return {"deleted": 0, "bytes_freed": 0}
    cutoff = time.time() - days * 86400
    deleted = 0
    bytes_freed = 0
    for p in cache_dir.glob("*.mp3"):
        try:
            st = p.stat()
            if st.st_mtime < cutoff:
                bytes_freed += st.st_size
                p.unlink()
                deleted += 1
        except OSError:
            pass
    return {"deleted": deleted, "bytes_freed": bytes_freed}


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

    # OpenAI 4096 chars 上限 — 在 orion_model.audio.tts 也會擋,這裡為了好錯誤
    # 訊息先 check(直接回 sidecar 自己 error code)
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
    char_count = len(text)

    # ─── Cache 查詢(sidecar 端 ~/.orion/tts-cache/)──────────────
    # 不走 orion_model.audio 是因為 cache 路徑 / mtime 都跟 Cowork 既有
    # blobs / plans GC 對齊,屬於 host 範疇。Cache key 含 model+voice+speed
    # +format+text → 同樣 sha256 → 同 mp3 檔。
    cache_key = _cache_key(
        text=text, model=model, voice=voice, speed=speed, audio_format=audio_format,
    )
    cache_dir = _tts_cache_dir()
    cache_file = cache_dir / f"{cache_key}.mp3"
    if cache_file.exists():
        try:
            audio_bytes = cache_file.read_bytes()
            cache_file.touch()  # 更新 mtime 讓 GC 不誤殺
            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
            yield {
                "event": "tts_synthesized",
                "data": {
                    "audio_base64": audio_b64,
                    "mime_type": mime,
                    "provider": provider,
                    "model": model,
                    "voice": voice,
                    "char_count": char_count,
                    "cost_usd": 0.0,
                    "cache_hit": True,
                },
                "final": True,
            }
            return
        except OSError:
            pass  # Cache 讀失敗 fall through 走 audio_synthesize

    # ─── 真正去合成(env-gate:proxy / direct)──────────────────────
    try:
        result = await audio_synthesize(
            provider=provider,
            model=model,
            voice=voice,
            speed=speed,
            text=text,
            audio_format=audio_format,
        )
    except ValueError as e:
        yield _err("BAD_PARAMS", str(e))
        return
    except RuntimeError as e:
        yield _err("API_FAILED", str(e))
        return

    # 寫進 cache — fail 不影響回應
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(result.audio_bytes)
    except OSError:
        pass

    audio_b64 = base64.b64encode(result.audio_bytes).decode("ascii")
    yield {
        "event": "tts_synthesized",
        "data": {
            "audio_base64": audio_b64,
            "mime_type": result.mime_type,
            "provider": result.provider,
            "model": result.model,
            "voice": result.voice,
            "char_count": result.char_count,
            "cost_usd": result.cost_usd,
            "cache_hit": False,
        },
        "final": True,
    }


async def tts_status(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:  # noqa: ARG001
    """回 TTS 可用狀態 + catalog + 各 provider 是否有 API key。Settings UI 用。"""
    from orion_model.tts_catalog import list_tts_catalog

    catalog = list_tts_catalog()
    # OpenAI TTS 走 proxy 時 client 不必直接有 OPENAI_API_KEY — proxy 那邊有。
    openai_via_proxy = bool(os.environ.get("ORION_MODEL_PROXY_URL"))
    providers_meta = []
    for p in catalog.get("providers", []) or []:
        pid = p.get("id") if isinstance(p, dict) else None
        has_key = False
        via_proxy = False
        if pid == "openai":
            if openai_via_proxy:
                has_key = True
                via_proxy = True
            else:
                has_key = bool(os.environ.get("OPENAI_API_KEY"))
        providers_meta.append({
            "id": pid,
            "label": p.get("label") if isinstance(p, dict) else pid,
            "models": p.get("models") if isinstance(p, dict) else [],
            "voices": p.get("voices") if isinstance(p, dict) else [],
            "api_key_configured": has_key,
            "via_proxy": via_proxy,
        })
    yield {
        "event": "tts_status",
        "data": {"providers": providers_meta},
        "final": True,
    }


__all__ = [
    "tts_synthesize",
    "tts_status",
    "get_tts_voices",
    "cleanup_old_tts_cache",
]
