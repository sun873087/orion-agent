"""llm/catalog.py — model allowlist 驗證 + per-model attribute getters + JSON loader。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_model.catalog import (
    find_pricing_by_model,
    get_max_context_tokens,
    get_max_output_tokens,
    get_pricing,
    get_supports_reasoning,
    iter_all_entries,
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
    assert validate("openai", "gpt-5-mini")
    assert validate("openai", "gpt-5.5")


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
    # 4 個 provider:anthropic / openai / ollama / openrouter(全來自 models.json static)
    assert ids == {"anthropic", "openai", "ollama", "openrouter"}
    for p in providers:  # type: ignore[union-attr]
        assert "label" in p
        assert "models" in p
        assert isinstance(p["models"], list)
        for m in p["models"]:
            assert "id" in m
            assert "label" in m
            assert isinstance(m["max_output_tokens"], int)
            assert isinstance(m["max_context_tokens"], int)
            assert isinstance(m["supports_reasoning"], bool)
            assert "pricing" in m
            assert "input" in m["pricing"]
            assert "output" in m["pricing"]
            assert "cache_read" in m["pricing"]


def test_get_max_output_tokens_known() -> None:
    assert get_max_output_tokens("anthropic", "claude-sonnet-4-6") == 64000
    assert get_max_output_tokens("anthropic", "claude-haiku-4-5") == 8192


def test_get_max_output_tokens_unknown() -> None:
    assert get_max_output_tokens("anthropic", "claude-fake") is None
    assert get_max_output_tokens("nope", "x") is None


def test_get_max_context_tokens() -> None:
    assert get_max_context_tokens("anthropic", "claude-sonnet-4-6") == 200_000
    assert get_max_context_tokens("openai", "gpt-5") == 1_000_000
    assert get_max_context_tokens("openai", "gpt-5-mini") == 1_000_000
    assert get_max_context_tokens("anthropic", "fake") is None


def test_get_supports_reasoning() -> None:
    # Reasoning-supporting models
    assert get_supports_reasoning("anthropic", "claude-opus-4-7") is True
    assert get_supports_reasoning("openai", "gpt-5.5") is True
    assert get_supports_reasoning("openai", "gpt-5") is True
    # Non-reasoning models — 目前 catalog 內 OpenAI 全是 reasoning 系列,
    # 只剩 Anthropic Sonnet 是 non-reasoning(Opus / Haiku 4.5 都 reasoning)。
    assert get_supports_reasoning("anthropic", "claude-sonnet-4-6") is False
    # Unknown → False (safe default)
    assert get_supports_reasoning("anthropic", "fake") is False


def test_get_pricing_known() -> None:
    p = get_pricing("anthropic", "claude-opus-4-7")
    assert p == {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_creation": 18.75}
    # OpenAI 沒 cache_creation
    o = get_pricing("openai", "gpt-5")
    assert o is not None and "cache_creation" not in o
    assert o["input"] == 2.5


def test_get_pricing_unknown() -> None:
    assert get_pricing("anthropic", "fake") is None
    assert get_pricing("nope", "x") is None


def test_find_pricing_by_model_reverse_lookup() -> None:
    # Used by cost_tracker which only has model name, not provider
    p = find_pricing_by_model("claude-haiku-4-5")
    assert p is not None and p["input"] == 1.0
    p = find_pricing_by_model("gpt-5-mini")
    assert p is not None and p["input"] == 0.25
    assert find_pricing_by_model("not-a-model") is None


def test_iter_all_entries_flat_list() -> None:
    entries = iter_all_entries()
    ids = {e["id"] for e in entries}
    # both providers' models flattened together
    assert "claude-sonnet-4-6" in ids
    assert "gpt-5" in ids
    assert "gpt-5-mini" in ids


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
                                "max_context_tokens": 500000,
                                "supports_reasoning": True,
                                "pricing": {
                                    "input": 20.0,
                                    "output": 100.0,
                                    "cache_read": 2.0,
                                    "cache_creation": 25.0,
                                },
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
        assert get_max_context_tokens("anthropic", "claude-future-99") == 500000
        assert get_supports_reasoning("anthropic", "claude-future-99") is True
        # 原本 packaged 內的不存在了(override 完全覆蓋)
        assert not validate("anthropic", "claude-sonnet-4-6")
    finally:
        reset_cache_for_tests()


def test_json_invalid_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{not valid json")
    monkeypatch.setenv("ORION_MODELS_FILE", str(p))
    reset_cache_for_tests()
    try:
        # parse 失敗 → fallback 到 packaged,sonnet 還在
        assert validate("anthropic", "claude-sonnet-4-6")
    finally:
        reset_cache_for_tests()


def test_json_partial_schema_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Override 缺必填欄位(e.g. 沒 pricing) → 整個檔被拒,fallback packaged。"""
    p = tmp_path / "partial.json"
    p.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "id": "anthropic",
                        "models": [
                            # 缺 max_context_tokens 跟 pricing
                            {"id": "claude-x", "label": "X", "max_output_tokens": 1000},
                        ],
                    },
                ],
            },
        ),
    )
    monkeypatch.setenv("ORION_MODELS_FILE", str(p))
    reset_cache_for_tests()
    try:
        assert not validate("anthropic", "claude-x")  # rejected
        assert validate("anthropic", "claude-sonnet-4-6")  # fallback worked
    finally:
        reset_cache_for_tests()
