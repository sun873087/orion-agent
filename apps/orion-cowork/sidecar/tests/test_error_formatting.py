"""驗證 `_format_send_error` 把 SDK 例外解成 user-friendly (code, message),
不會 ⚠ {"code":"ExceptionGroup",...} 給 UI。"""

from __future__ import annotations

import pytest

from orion_cowork_sidecar.handlers import _format_send_error, _unwrap_exception


class _FakeAuthError(Exception):
    """模擬 anthropic.AuthenticationError / openai.AuthenticationError。"""

    status_code = 401

    def __init__(self, msg: str) -> None:
        super().__init__(msg)


class _FakePermissionError(Exception):
    status_code = 403


class _FakeRateLimitError(Exception):
    status_code = 429


class _FakeConnectError(Exception):
    pass


# 改名讓 _format_send_error 認到
_FakeAuthError.__name__ = "AuthenticationError"
_FakePermissionError.__name__ = "PermissionDeniedError"
_FakeRateLimitError.__name__ = "RateLimitError"
_FakeConnectError.__name__ = "APIConnectionError"


def test_unwrap_exception_group_single() -> None:
    inner = _FakeAuthError("invalid key")
    group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])
    assert _unwrap_exception(group) is inner


def test_unwrap_nested_groups() -> None:
    deepest = _FakeAuthError("invalid key")
    g1 = ExceptionGroup("inner", [deepest])
    g2 = ExceptionGroup("outer", [g1])
    assert _unwrap_exception(g2) is deepest


def test_unwrap_multi_sub_exception_keeps_group() -> None:
    """多 sub-exception 時不解 — 避免吞掉其他錯。"""
    a = ValueError("a")
    b = TypeError("b")
    group = ExceptionGroup("two", [a, b])
    assert _unwrap_exception(group) is group


def test_format_auth_error_via_class_name() -> None:
    code, msg = _format_send_error(_FakeAuthError("Error code: 401"))
    assert code == "AUTH_FAILED"
    assert "認證失敗" in msg or "API key" in msg


def test_format_auth_via_status_code() -> None:
    """status_code=401 即使 class name 不對也 catch。"""
    class _Weird(Exception):
        status_code = 401
    _Weird.__name__ = "WeirdError"
    code, msg = _format_send_error(_Weird("oops"))
    assert code == "AUTH_FAILED"


def test_format_permission_denied() -> None:
    code, msg = _format_send_error(_FakePermissionError("revoked"))
    assert code == "PERMISSION_DENIED"
    assert "revoke" in msg


def test_format_rate_limit() -> None:
    code, _ = _format_send_error(_FakeRateLimitError("rate"))
    assert code == "RATE_LIMIT"


def test_format_402_budget() -> None:
    class _Cap(Exception):
        status_code = 402
    code, msg = _format_send_error(_Cap("budget cap reached"))
    assert code == "BUDGET_EXCEEDED"


def test_format_connect_error() -> None:
    code, msg = _format_send_error(_FakeConnectError("connection refused"))
    assert code == "CONNECTION_FAILED"
    assert "proxy" in msg.lower()


def test_format_exception_group_with_auth_inside() -> None:
    """重現用戶截圖場景:`{"code":"ExceptionGroup",...}` 不該流到 user。"""
    inner = _FakeAuthError("Error code: 401 - {'error': 'invalid API key'}")
    group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])
    code, msg = _format_send_error(group)
    assert code == "AUTH_FAILED"
    assert "ExceptionGroup" not in msg
    assert "TaskGroup" not in msg


def test_format_unknown_error_truncates() -> None:
    """完全不認識的例外 — fallback 用 type name + 截短 str,不爆 UI。"""
    class _Mystery(Exception):
        pass
    _Mystery.__name__ = "MysteryThing"
    long = "x" * 500
    code, msg = _format_send_error(_Mystery(long))
    assert code == "MysteryThing"
    assert len(msg) <= 300
