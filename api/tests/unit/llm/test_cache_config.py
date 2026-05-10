"""cache_config — TTL 設定 + cache_control 產生邏輯。"""

from __future__ import annotations

import pytest

from orion_agent.llm.cache_config import (
    CacheTTLConfig,
    build_cache_control,
    load_cache_ttl_config,
)


def test_default_config_static_session_1h_messages_5m() -> None:
    """無 env vars → 預設(static/session 1h,messages 5m)。"""
    cfg = CacheTTLConfig()
    assert cfg.static == "1h"
    assert cfg.session == "1h"
    assert cfg.messages == "5m"


def test_load_with_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_CACHE_TTL_STATIC", "5m")
    monkeypatch.setenv("ORION_CACHE_TTL_SESSION", "5m")
    monkeypatch.setenv("ORION_CACHE_TTL_MESSAGES", "1h")
    cfg = load_cache_ttl_config()
    assert cfg.static == "5m"
    assert cfg.session == "5m"
    assert cfg.messages == "1h"


def test_load_invalid_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """無效 TTL → 靜默 fallback 到預設,不 crash。"""
    monkeypatch.setenv("ORION_CACHE_TTL_STATIC", "30m")  # 不支援
    monkeypatch.setenv("ORION_CACHE_TTL_SESSION", "garbage")
    cfg = load_cache_ttl_config()
    assert cfg.static == "1h"  # 預設
    assert cfg.session == "1h"  # 預設


def test_load_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_CACHE_TTL_STATIC", "1H")
    monkeypatch.setenv("ORION_CACHE_TTL_MESSAGES", "5M")
    cfg = load_cache_ttl_config()
    assert cfg.static == "1h"
    assert cfg.messages == "5m"


def test_build_cache_control_5m_no_ttl_field() -> None:
    """5m 是預設,不需要帶 ttl 欄位。"""
    cc = build_cache_control("5m")
    assert cc == {"type": "ephemeral"}


def test_build_cache_control_1h_includes_ttl() -> None:
    """1h 必須帶 ttl 欄位 — 否則 API 用預設 5m。"""
    cc = build_cache_control("1h")
    assert cc == {"type": "ephemeral", "ttl": "1h"}


def test_load_unset_uses_dataclass_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORION_CACHE_TTL_STATIC", raising=False)
    monkeypatch.delenv("ORION_CACHE_TTL_SESSION", raising=False)
    monkeypatch.delenv("ORION_CACHE_TTL_MESSAGES", raising=False)
    cfg = load_cache_ttl_config()
    assert cfg == CacheTTLConfig()
