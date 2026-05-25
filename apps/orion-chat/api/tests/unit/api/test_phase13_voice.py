"""Phase 13 — voice status / 端點守門。

真實 STT/TTS 合成需 provider SDK + per-tenant key(見路線圖風險項),未配置時 503。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


@pytest.fixture
def client_with_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    # 不設任何 voice key → 不可用
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    with TestClient(create_app()) as client:
        client.post("/auth/register", json={"username": "a", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"username": "a", "password": "pw123456"},
        ).json()["token"]
        yield client, token


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_voice_status_unavailable(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.get("/voice/status", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {"tts_available": False, "stt_available": False}


def test_tts_503_when_unconfigured(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.post("/voice/tts", headers=_h(token), json={"text": "hi"})
    assert r.status_code == 503


def test_tts_available_when_key_set(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, token = client_with_token
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    assert (
        client.get("/voice/status", headers=_h(token)).json()["tts_available"]
        is True
    )


def test_tts_synthesizes_when_key_set(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """設了 key → 走 orion_model.audio.synthesize(stub),回 base64 audio。"""
    client, token = client_with_token
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    from orion_model.audio.types import SynthesizeResult

    async def fake_synth(**_kwargs: object) -> SynthesizeResult:
        return SynthesizeResult(
            audio_bytes=b"\x00\x01\x02ID3",
            mime_type="audio/mpeg",
            provider="openai",
            model="tts-1",
            voice="nova",
            char_count=5,
            cost_usd=0.0001,
        )

    monkeypatch.setattr("orion_model.audio.synthesize", fake_synth)
    r = client.post("/voice/tts", headers=_h(token), json={"text": "hello"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mime_type"] == "audio/mpeg"
    import base64

    assert base64.b64decode(body["audio_base64"]) == b"\x00\x01\x02ID3"


def test_stt_503_when_unconfigured(
    client_with_token: tuple[TestClient, str],
) -> None:
    client, token = client_with_token
    r = client.post(
        "/voice/stt", headers=_h(token), json={"audio_base64": "AAAA"},
    )
    assert r.status_code == 503


def test_stt_transcribes_when_key_set(
    client_with_token: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """設了 key → 走 orion_model.audio.transcribe(這裡 stub,不打真 API)。"""
    client, token = client_with_token
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    from orion_model.audio.types import TranscribeResult

    async def fake_transcribe(**_kwargs: object) -> TranscribeResult:
        return TranscribeResult(
            text="hello world",
            provider="openai",
            model="whisper-1",
            duration_seconds=1.0,
            cost_usd=0.0001,
        )

    monkeypatch.setattr("orion_model.audio.transcribe", fake_transcribe)
    r = client.post(
        "/voice/stt",
        headers=_h(token),
        json={"audio_base64": "AAAA", "mime_type": "audio/webm"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "hello world"
