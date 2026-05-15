"""memory/paths.py。"""

from __future__ import annotations

from orion_sdk.memory.paths import (
    default_user_id,
    user_memory_paths,
)


def test_default_user_id_default(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("ORION_USER_ID", raising=False)
    assert default_user_id() == "default"


def test_default_user_id_env_override(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("ORION_USER_ID", "alice")
    assert default_user_id() == "alice"


def test_user_memory_paths_layout(tmp_path) -> None:  # noqa: ANN001
    p = user_memory_paths("bob", users_root=tmp_path)
    assert p.user_id == "bob"
    assert p.root == tmp_path / "bob"
    assert p.memory_dir == tmp_path / "bob" / "memory"
    assert p.index == tmp_path / "bob" / "memory" / "MEMORY.md"


def test_ensure_dirs_creates(tmp_path) -> None:  # noqa: ANN001
    p = user_memory_paths("bob", users_root=tmp_path)
    p.ensure_dirs()
    assert p.memory_dir.is_dir()
    p.ensure_dirs()  # idempotent


def test_users_dir_env(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path))
    p = user_memory_paths("xx")
    assert str(tmp_path) in str(p.root)
