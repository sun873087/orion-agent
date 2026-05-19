"""Phase 31-T:TTS cache 驗證。

不打真 OpenAI — monkeypatch httpx.AsyncClient.post 回固定 fake audio bytes。
驗證:
  1. Miss → 打 OpenAI 一次,寫 cache 檔
  2. 再 call 同樣 (text, voice, speed, model) → 不打 OpenAI,cache_hit=True,
     cost_usd=0
  3. 不同 voice / speed / text → cache miss(各自分開)
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest

from orion_cowork_sidecar import tts_handlers


class _FakeResp:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.text = ""


class _FakeClient:
    """Stub httpx.AsyncClient — counter 記實際打了幾次 OpenAI。"""

    call_count = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, headers=None, json=None):
        _FakeClient.call_count += 1
        return _FakeResp(b"FAKE_AUDIO_BYTES_" + str(_FakeClient.call_count).encode())


async def _consume(gen: AsyncIterator) -> list[dict]:
    out = []
    async for f in gen:
        out.append(f)
    return out


@pytest.fixture
def tts_env():
    """Tmpdir + fake OPENAI_API_KEY,each test 獨立 cache。"""
    with tempfile.TemporaryDirectory(prefix="tts-cache-test-") as d:
        old_env = os.environ.get("ORION_COWORK_DATA_DIR")
        old_key = os.environ.get("OPENAI_API_KEY")
        os.environ["ORION_COWORK_DATA_DIR"] = d
        os.environ["OPENAI_API_KEY"] = "sk-test-fake-key"
        _FakeClient.call_count = 0
        try:
            yield Path(d)
        finally:
            if old_env is None:
                os.environ.pop("ORION_COWORK_DATA_DIR", None)
            else:
                os.environ["ORION_COWORK_DATA_DIR"] = old_env
            if old_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_key


@pytest.mark.asyncio
async def test_tts_cache_hit_avoids_openai(tts_env: Path) -> None:
    """同樣 (text, voice, speed, model) → 第二次走 cache,不打 OpenAI。"""
    params = {
        "provider": "openai",
        "model": "tts-1",
        "voice": "nova",
        "speed": 1.0,
        "text": "hello world",
        "format": "mp3",
    }
    with patch("httpx.AsyncClient", _FakeClient):
        # 第一次 — miss
        frames1 = await _consume(tts_handlers.tts_synthesize(params))
        assert frames1[0]["event"] == "tts_synthesized"
        assert frames1[0]["data"]["cache_hit"] is False
        assert frames1[0]["data"]["cost_usd"] > 0
        assert _FakeClient.call_count == 1

        # 第二次 — hit,cost=0,call_count 不變
        frames2 = await _consume(tts_handlers.tts_synthesize(params))
        assert frames2[0]["event"] == "tts_synthesized"
        assert frames2[0]["data"]["cache_hit"] is True
        assert frames2[0]["data"]["cost_usd"] == 0.0
        assert _FakeClient.call_count == 1, "cache hit 不該再打 OpenAI"

        # 內容一致(audio bytes 同 hash)
        assert frames1[0]["data"]["audio_base64"] == frames2[0]["data"]["audio_base64"]


@pytest.mark.asyncio
async def test_tts_cache_miss_on_different_params(tts_env: Path) -> None:
    """不同 voice / speed / text 各自獨立 cache,不會誤命中。"""
    base = {
        "provider": "openai",
        "model": "tts-1",
        "voice": "nova",
        "speed": 1.0,
        "text": "A",
        "format": "mp3",
    }
    with patch("httpx.AsyncClient", _FakeClient):
        await _consume(tts_handlers.tts_synthesize(base))
        # 換 text
        await _consume(tts_handlers.tts_synthesize({**base, "text": "B"}))
        # 換 voice
        await _consume(tts_handlers.tts_synthesize({**base, "voice": "echo"}))
        # 換 speed
        await _consume(tts_handlers.tts_synthesize({**base, "speed": 1.5}))
        # 換 model
        await _consume(tts_handlers.tts_synthesize({**base, "model": "tts-1-hd"}))
        assert _FakeClient.call_count == 5, "5 個不同參數應各打 OpenAI 一次"
