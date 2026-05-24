"""Phase 1 — skills / roles / soul 的 per-user CRUD + soul 注入。

isolation:把 skills / roles / memory(soul)的 root 全指到 tmp,並把 system
skills dir 也指到不存在的 tmp,避免 host 的 ~/.orion 漏進測試。bundled skills /
roles 仍會載入(來自 package),所以斷言用「包含」而非「等於」。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app
from orion_chat_api.user_context import build_user_system_prefix, write_soul


@pytest.fixture
def assets_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[tuple[TestClient, str, Path, str]]:
    """回 (client, token, users_root, user_id)。"""
    users = tmp_path / "users"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(users))
    monkeypatch.setenv("ORION_USER_SKILLS_DIR", str(users))
    monkeypatch.setenv("ORION_USER_ROLES_DIR", str(users))
    # system skills 指到不存在 tmp,避免漏 host ~/.orion/skills
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path / "system_skills"))
    with TestClient(create_app()) as client:
        client.post(
            "/auth/register", json={"username": "alice", "password": "passw0rd"},
        )
        login = client.post(
            "/auth/login", json={"username": "alice", "password": "passw0rd"},
        ).json()
        yield client, login["token"], users, login["user_id"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── skills ──────────────────────────────────────────────────────────────


def test_skill_put_creates_file_and_lists(
    assets_client: tuple[TestClient, str, Path, str],
) -> None:
    client, token, users_root, user_id = assets_client
    r = client.put(
        "/skills/my-skill",
        headers=_h(token),
        json={"description": "does a thing", "body": "# My Skill\n\nsteps..."},
    )
    assert r.status_code == 200, r.json()
    assert r.json()["editable"] is True

    md = users_root / user_id / "skills" / "my-skill" / "SKILL.md"
    assert md.is_file()
    text = md.read_text()
    assert "name: my-skill" in text
    assert "# My Skill" in text

    listing = client.get("/skills", headers=_h(token)).json()
    mine = [s for s in listing if s["name"] == "my-skill"]
    assert len(mine) == 1 and mine[0]["editable"] is True


def test_skill_get_after_put(
    assets_client: tuple[TestClient, str, Path, str],
) -> None:
    client, token, _, _ = assets_client
    client.put(
        "/skills/greeter",
        headers=_h(token),
        json={"description": "greets", "body": "say hi", "cowork_visible": False},
    )
    body = client.get("/skills/greeter", headers=_h(token)).json()
    assert body["body"] == "say hi"
    assert body["cowork_visible"] is False
    assert body["editable"] is True


def test_skill_delete_idempotent(
    assets_client: tuple[TestClient, str, Path, str],
) -> None:
    client, token, _, _ = assets_client
    client.put("/skills/tmp", headers=_h(token), json={"description": "x", "body": "y"})
    assert client.delete("/skills/tmp", headers=_h(token)).json() == {"deleted": True}
    assert client.delete("/skills/tmp", headers=_h(token)).json() == {"deleted": False}
    assert client.get("/skills/tmp", headers=_h(token)).status_code == 404


def test_skill_invalid_name(
    assets_client: tuple[TestClient, str, Path, str],
) -> None:
    client, token, _, _ = assets_client
    r = client.put("/skills/bad@name", headers=_h(token), json={"description": "x"})
    assert r.status_code == 422


# ── roles ───────────────────────────────────────────────────────────────


def test_role_put_creates_and_lists(
    assets_client: tuple[TestClient, str, Path, str],
) -> None:
    client, token, users_root, user_id = assets_client
    r = client.put(
        "/roles/backend",
        headers=_h(token),
        json={
            "description": "backend specialist",
            "body": "You focus on APIs.",
            "default_disabled_tools": ["WebSearch"],
            "default_permission_mode": "act",
        },
    )
    assert r.status_code == 200, r.json()
    md = users_root / user_id / "roles" / "backend" / "ROLE.md"
    assert md.is_file()

    detail = client.get("/roles/backend", headers=_h(token)).json()
    assert detail["body"] == "You focus on APIs."
    assert detail["default_disabled_tools"] == ["WebSearch"]
    assert detail["default_permission_mode"] == "act"
    assert detail["editable"] is True


def test_role_delete(
    assets_client: tuple[TestClient, str, Path, str],
) -> None:
    client, token, _, _ = assets_client
    client.put("/roles/tmp", headers=_h(token), json={"description": "x", "body": "y"})
    assert client.delete("/roles/tmp", headers=_h(token)).json() == {"deleted": True}
    assert client.get("/roles/tmp", headers=_h(token)).status_code == 404


# ── soul ────────────────────────────────────────────────────────────────


def test_soul_put_get_delete(
    assets_client: tuple[TestClient, str, Path, str],
) -> None:
    client, token, users_root, user_id = assets_client
    assert client.get("/me/soul", headers=_h(token)).json() == {"content": ""}

    r = client.put(
        "/me/soul", headers=_h(token), json={"content": "They love type hints."},
    )
    assert r.status_code == 200
    assert "type hints" in r.json()["content"]
    soul_file = users_root / user_id / "memory" / "soul.md"
    assert soul_file.is_file()

    assert "type hints" in client.get("/me/soul", headers=_h(token)).json()["content"]

    client.delete("/me/soul", headers=_h(token))
    assert client.get("/me/soul", headers=_h(token)).json() == {"content": ""}
    assert not soul_file.exists()


def test_soul_injected_into_system_prefix(
    assets_client: tuple[TestClient, str, Path, str],
) -> None:
    """write_soul → build_user_system_prefix 含 soul;沒 soul 回空字串。"""
    _, _, _, user_id = assets_client
    assert build_user_system_prefix(user_id) == ""
    write_soul("They prefer terse answers.", user_id)
    prefix = build_user_system_prefix(user_id)
    assert "They prefer terse answers." in prefix
    assert "What you remember about this person" in prefix


# ── cross-user isolation ──────────────────────────────────────────────────


def test_cross_user_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    users = tmp_path / "users"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(users))
    monkeypatch.setenv("ORION_USER_SKILLS_DIR", str(users))
    monkeypatch.setenv("ORION_USER_ROLES_DIR", str(users))
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path / "system_skills"))

    with TestClient(create_app()) as client:
        for uname in ("alice", "bob"):
            client.post(
                "/auth/register", json={"username": uname, "password": "passw0rd"},
            )
        alice_t = client.post(
            "/auth/login", json={"username": "alice", "password": "passw0rd"},
        ).json()["token"]
        bob_t = client.post(
            "/auth/login", json={"username": "bob", "password": "passw0rd"},
        ).json()["token"]

        client.put(
            "/skills/secret-skill", headers=_h(alice_t),
            json={"description": "private", "body": "x"},
        )
        client.put("/me/soul", headers=_h(alice_t), json={"content": "alice soul"})

        # bob 看不到 alice 的 skill
        bob_skills = {s["name"] for s in client.get("/skills", headers=_h(bob_t)).json()}
        assert "secret-skill" not in bob_skills
        assert client.get("/skills/secret-skill", headers=_h(bob_t)).status_code == 404
        # bob 的 soul 仍空
        assert client.get("/me/soul", headers=_h(bob_t)).json() == {"content": ""}
