"""ProviderHTTPError(orion_model.errors)— status code → 中文友善訊息。"""

from __future__ import annotations

import pytest

from orion_model.errors import ProviderHTTPError


def test_429_google_specific_quota_hint() -> None:
    e = ProviderHTTPError(provider="google", status_code=429)
    msg = str(e)
    assert "Gemini" in msg
    assert "配額" in msg or "quota" in msg.lower()
    assert "RPM" in msg # free tier 提示
    assert e.status_code == 429


def test_429_other_provider_generic() -> None:
    e = ProviderHTTPError(provider="ollama", status_code=429)
    assert "速率" in str(e) or "quota" in str(e).lower()


def test_401_auth_key_hint() -> None:
    e = ProviderHTTPError(provider="google", status_code=401)
    assert "API key" in str(e)


def test_403_permission() -> None:
    e = ProviderHTTPError(provider="google", status_code=403)
    msg = str(e)
    assert "權限" in msg or "revoke" in msg or "enable" in msg


def test_404_model_hint_without_upstream_msg() -> None:
    e = ProviderHTTPError(provider="google", status_code=404)
    assert "model" in str(e).lower() or "拼錯" in str(e)


def test_400_includes_upstream_message() -> None:
    e = ProviderHTTPError(
        provider="google", status_code=400,
        upstream_message="Unknown name 'exclusiveMinimum'",
    )
    assert "exclusiveMinimum" in str(e)


def test_400_without_upstream_msg() -> None:
    e = ProviderHTTPError(provider="google", status_code=400)
    assert "400" in str(e)


def test_500_class_includes_status_and_msg() -> None:
    e = ProviderHTTPError(
        provider="google", status_code=503,
        upstream_message="model overloaded",
    )
    msg = str(e)
    assert "503" in msg
    assert "overloaded" in msg


def test_body_truncated_to_1kb() -> None:
    """upstream body 太長(萬字 JSON)→ 截 1KB 不要爆 logs / DB。"""
    huge = "x" * 5000
    e = ProviderHTTPError(provider="google", status_code=500, body=huge)
    assert len(e.body) == 1000


def test_attributes_preserved() -> None:
    """typed exception attributes 完整 — sidecar `_format_send_error` 靠它分類。"""
    e = ProviderHTTPError(
        provider="google", status_code=402,
        upstream_message="billing required", body='{"error":"x"}',
    )
    assert e.provider == "google"
    assert e.status_code == 402
    assert e.upstream_message == "billing required"
    assert e.body == '{"error":"x"}'


def test_is_runtime_error_subclass() -> None:
    """sidecar `except Exception` path 也能 catch — 必須是 BaseException 後裔。"""
    e = ProviderHTTPError(provider="x", status_code=500)
    assert isinstance(e, RuntimeError)
    assert isinstance(e, Exception)


def test_raise_and_catch_by_status_code() -> None:
    """整合驗 raise → catch → 拿 status_code 套 mapping。"""
    with pytest.raises(ProviderHTTPError) as exc_info:
        raise ProviderHTTPError(provider="google", status_code=429)
    assert exc_info.value.status_code == 429
