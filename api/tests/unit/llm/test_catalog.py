"""llm/catalog.py — model allowlist 驗證 + listing + JSON loader。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_agent.llm.catalog import (
    get_max_output_tokens,
    list_catalog,
    reset_cache_for_tests,
    validate,
)


def test_validate_known_anthropic_models() -> None:
    assert validate("anthropic", "claude-opus-4-7")
    assert validate("anthropic", "claude-sonnet-4-6")
    assert validate("anthropic", "claude-haiku-4-5")


def test_validate_known_openai_models() -> None:
    assert validate("openai", "gpt-5")
    assert validate("openai", "gpt-4o-mini")
    assert validate("openai", "o3")


def test_validate_unknown_provider() -> None:
    assert not validate("google", "gemini-2.5")


def test_validate_unknown_model() -> None:
    assert not validate("anthropic", "claude-fake-99")
    assert not validate("openai", "gpt-99")


def test_validate_cross_provider_pair_rejected() -> None:
    """anthropic + gpt-5 應該擋(防止 client 亂組)。"""
    assert not validate("anthropic", "gpt-5")
    assert not validate("openai", "claude-opus-4-7")


def test_list_catalog_shape() -> None:
    cat = list_catalog()
    assert "providers" in cat
    providers = cat["providers"]
    assert isinstance(providers, list)
    ids = {p["id"] for p in providers}  # type: ignore[index]
    assert ids == {"anthropic", "openai"}
    for p in providers:  # type: ignore[union-attr]
        assert "label" in p
        assert "models" in p
        assert isinstance(p["models"], list)
        for m in p["models"]:
            assert "id" in m
            assert "label" in m
            assert "max_output_tokens" in m
            assert isinstance(m["max_output_tokens"], int)


def test_get_max_output_tokens_known() -> None:
    # 從 default models.json (or built-in fallback) 應該都有 sensible 值
    assert get_max_output_tokens("anthropic", "claude-sonnet-4-6") == 64000
    assert get_max_output_tokens("anthropic", "claude-haiku-4-5") == 8192


def test_get_max_output_tokens_unknown() -> None:
    assert get_max_output_tokens("anthropic", "claude-fake") is None
    assert get_max_output_tokens("nope", "x") is None


def test_json_override_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "custom.json"
    p.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "anthropic",
                        "label": "Anthropic",
                        "models": [
                            {
                                "id": "claude-future-99",
                                "label": "Claude Future 99",
                                "max_output_tokens": 200000,
                            },
                        ],
                    },
                ],
            },
        ),
    )
    monkeypatch.setenv("ORION_MODELS_FILE", str(p))
    reset_cache_for_tests()
    try:
        assert validate("anthropic", "claude-future-99")
        assert get_max_output_tokens("anthropic", "claude-future-99") == 200000
        # 原本內建的就不存在了(JSON 完全覆蓋)
        assert not validate("anthropic", "claude-sonnet-4-6")
    finally:
        reset_cache_for_tests()


def test_json_invalid_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{not valid json")
    monkeypatch.setenv("ORION_MODELS_FILE", str(p))
    reset_cache_for_tests()
    try:
        # parse 失敗 → 用內建,sonnet 還在
        assert validate("anthropic", "claude-sonnet-4-6")
    finally:
        reset_cache_for_tests()
