"""sandbox factory 行為:env / 名稱選擇 backend。"""

from __future__ import annotations

import pytest

from orion_sdk.sandbox.factory import get_sandbox_backend
from orion_sdk.sandbox.local import LocalBackend
from orion_sdk.sandbox.protocol import SandboxError


def test_default_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORION_SANDBOX", raising=False)
    backend = get_sandbox_backend()
    assert isinstance(backend, LocalBackend)


def test_explicit_local() -> None:
    backend = get_sandbox_backend("local")
    assert isinstance(backend, LocalBackend)


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_SANDBOX", "local")
    backend = get_sandbox_backend()
    assert isinstance(backend, LocalBackend)


def test_unknown_backend_raises() -> None:
    with pytest.raises(SandboxError):
        get_sandbox_backend("nope")
