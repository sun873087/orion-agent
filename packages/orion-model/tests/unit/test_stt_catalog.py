"""Unit tests for orion_model.stt_catalog — packaged JSON 走 importlib.resources。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_model import stt_catalog


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    stt_catalog.reset_cache_for_tests()
    yield
    stt_catalog.reset_cache_for_tests()


def test_packaged_catalog_has_openai_and_google() -> None:
    cat = stt_catalog.list_stt_catalog()
    providers = cat["providers"]
    assert isinstance(providers, list)
    ids = [p["id"] for p in providers]
    assert "openai" in ids
    assert "google" in ids


def test_openai_models_include_gpt4o_variants() -> None:
    cat = stt_catalog.list_stt_catalog()
    openai = next(p for p in cat["providers"] if p["id"] == "openai")
    model_ids = [m["id"] for m in openai["models"]]
    assert "whisper-1" in model_ids
    assert "gpt-4o-transcribe" in model_ids
    assert "gpt-4o-mini-transcribe" in model_ids


def test_validate_known_model() -> None:
    assert stt_catalog.validate_stt("openai", "gpt-4o-mini-transcribe") is True
    assert stt_catalog.validate_stt("openai", "whisper-1") is True
    assert stt_catalog.validate_stt("google", "default") is True


def test_validate_rejects_unknown() -> None:
    assert stt_catalog.validate_stt("openai", "nonexistent-model") is False
    assert stt_catalog.validate_stt("nonexistent", "default") is False


def test_pricing_returned() -> None:
    p = stt_catalog.get_stt_pricing("openai", "gpt-4o-mini-transcribe")
    assert p is not None
    assert p > 0
    assert stt_catalog.get_stt_pricing("openai", "nonexistent") is None


def test_runtime_override_via_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 自定義 minimal STT catalog,只給 fake provider
    override = tmp_path / "stt.json"
    override.write_text(
        json.dumps({
            "providers": [
                {
                    "id": "fake",
                    "label": "Fake",
                    "models": [
                        {"id": "model-a", "label": "Model A", "pricing_per_minute_usd": 0.01},
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORION_STT_MODELS_FILE", str(override))
    stt_catalog.reset_cache_for_tests()
    cat = stt_catalog.list_stt_catalog()
    assert [p["id"] for p in cat["providers"]] == ["fake"]
    assert stt_catalog.validate_stt("fake", "model-a") is True
    assert stt_catalog.validate_stt("openai", "whisper-1") is False
