"""llm/catalog.py — model allowlist 驗證 + listing。"""

from __future__ import annotations

from orion_agent.llm.catalog import MODELS, list_catalog, validate


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


def test_catalog_models_match_constants() -> None:
    """list_catalog 的內容該對得上 MODELS dict。"""
    cat = list_catalog()
    providers = {p["id"]: p for p in cat["providers"]}  # type: ignore[index,union-attr]
    for prov_id, entries in MODELS.items():
        listed = providers[prov_id]["models"]  # type: ignore[index]
        listed_ids = [m["id"] for m in listed]
        constant_ids = [e["id"] for e in entries]
        assert listed_ids == constant_ids
