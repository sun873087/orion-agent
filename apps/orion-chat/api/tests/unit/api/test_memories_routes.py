"""/me/memories REST CRUD。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orion_chat_api.app import create_app


@pytest.fixture
def client_with_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Iterator[tuple[TestClient, str, Path, str]]:
    """tmp ORION_USERS_DIR + DB 起 in-memory + 註冊登入拿 token。

    回 (client, token, users_root, user_id)。後 user fs 目錄 key
    是 users.id(UUID)而非 username,單測比對路徑時用 login response 的
    user_id,不可硬碼 "alice"。
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))
    with TestClient(create_app()) as client:
        client.post(
            "/auth/register", json={"username": "alice", "password": "passw0rd"},
        )
        login = client.post(
            "/auth/login", json={"username": "alice", "password": "passw0rd"},
        ).json()
        yield client, login["token"], tmp_path / "users", login["user_id"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_empty(client_with_token: tuple[TestClient, str, Path, str]) -> None:
    client, token, _, _ = client_with_token
    r = client.get("/me/memories", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == []


def test_put_creates_file_and_index(
    client_with_token: tuple[TestClient, str, Path, str],
) -> None:
    client, token, users_root, user_id = client_with_token
    r = client.put(
        "/me/memories/user_role.md",
        headers=_h(token),
        json={
            "name": "user is a Python engineer",
            "description": "writes mostly Python; prefers terse explanations",
            "type": "user",
            "body": "Likes type hints. Hates verbose docstrings.\n",
        },
    )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["filename"] == "user_role.md"
    assert body["type"] == "user"

    # fs 應該寫了檔
    user_dirs = list((users_root / user_id / "memory").glob("*.md"))
    files = {p.name for p in user_dirs}
    assert "user_role.md" in files
    assert "MEMORY.md" in files

    # MEMORY.md index 應該包含這條
    idx = (users_root / user_id / "memory" / "MEMORY.md").read_text()
    assert "user_role.md" in idx
    assert "user is a Python engineer" in idx


def test_get_after_put(
    client_with_token: tuple[TestClient, str, Path, str],
) -> None:
    client, token, _, _ = client_with_token
    client.put(
        "/me/memories/feedback_terse.md",
        headers=_h(token),
        json={
            "name": "no trailing summaries",
            "description": "user reads diffs; skip summary blocks at end",
            "type": "feedback",
            "body": "Why: stated explicitly.\nHow to apply: every response.\n",
        },
    )
    r = client.get("/me/memories/feedback_terse.md", headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "no trailing summaries"
    assert "Why: stated explicitly" in body["body"]
    assert body["type"] == "feedback"


def test_list_after_two_writes(
    client_with_token: tuple[TestClient, str, Path, str],
) -> None:
    client, token, _, _ = client_with_token
    for fname, name in [
        ("a.md", "alpha"),
        ("b.md", "beta"),
    ]:
        client.put(
            f"/me/memories/{fname}",
            headers=_h(token),
            json={"name": name, "description": f"desc {name}", "body": ""},
        )
    r = client.get("/me/memories", headers=_h(token))
    assert r.status_code == 200
    items = r.json()
    assert sorted(m["filename"] for m in items) == ["a.md", "b.md"]


def test_delete_removes_and_updates_index(
    client_with_token: tuple[TestClient, str, Path, str],
) -> None:
    client, token, users_root, user_id = client_with_token
    client.put(
        "/me/memories/temp.md",
        headers=_h(token),
        json={"name": "temp", "description": "to be deleted", "body": "x"},
    )
    r = client.delete("/me/memories/temp.md", headers=_h(token))
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    # idempotent — 再刪一次仍 200,但 deleted=False
    r2 = client.delete("/me/memories/temp.md", headers=_h(token))
    assert r2.status_code == 200
    assert r2.json() == {"deleted": False}

    # MEMORY.md 不應再含 temp
    idx_path = users_root / user_id / "memory" / "MEMORY.md"
    if idx_path.exists():
        assert "temp.md" not in idx_path.read_text()


def test_get_404(client_with_token: tuple[TestClient, str, Path, str]) -> None:
    client, token, _, _ = client_with_token
    r = client.get("/me/memories/nope.md", headers=_h(token))
    assert r.status_code == 404


def test_filename_traversal_blocked(
    client_with_token: tuple[TestClient, str, Path, str],
) -> None:
    client, token, _, _ = client_with_token
    # FastAPI 預設 path param 不接受 / — 這在 route layer 就會 404,但確認。
    # 我們的 sanitizer 主要擋 '..' / 怪字元;測單純不合法的名字
    r = client.put(
        "/me/memories/not-md.txt",
        headers=_h(token),
        json={"name": "x", "description": "y"},
    )
    assert r.status_code == 422


def test_memory_md_protected(
    client_with_token: tuple[TestClient, str, Path, str],
) -> None:
    """MEMORY.md 是 index,不該透過 REST 編輯。"""
    client, token, _, _ = client_with_token
    r = client.put(
        "/me/memories/MEMORY.md",
        headers=_h(token),
        json={"name": "x", "description": "y"},
    )
    assert r.status_code == 422


def test_put_with_expires_at_round_trips(
    client_with_token: tuple[TestClient, str, Path, str],
) -> None:
    """設定 expires_at 後 PUT → GET 應拿回同樣日期;檔案 frontmatter 也含此欄。"""
    client, token, users_root, user_id = client_with_token
    r = client.put(
        "/me/memories/project_q3.md",
        headers=_h(token),
        json={
            "name": "Q3 deadline",
            "description": "ship Q3 release",
            "type": "project",
            "expires_at": "2026-09-30",
            "body": "Release cut by end of Q3.\n",
        },
    )
    assert r.status_code == 200
    assert r.json()["expires_at"] == "2026-09-30"

    # GET 同樣回傳
    r_get = client.get(
        "/me/memories/project_q3.md", headers=_h(token),
    )
    assert r_get.json()["expires_at"] == "2026-09-30"

    # 檔案內 frontmatter 含 expires_at
    file_path = users_root / user_id / "memory" / "project_q3.md"
    text = file_path.read_text(encoding="utf-8")
    assert "expires_at: 2026-09-30" in text


def test_put_without_expires_at_returns_null(
    client_with_token: tuple[TestClient, str, Path, str],
) -> None:
    """未傳 expires_at → response 的欄位為 null,檔案不含該行。"""
    client, token, users_root, user_id = client_with_token
    r = client.put(
        "/me/memories/user_role.md",
        headers=_h(token),
        json={
            "name": "Role",
            "description": "engineer",
            "type": "user",
            "body": "...",
        },
    )
    assert r.status_code == 200
    assert r.json()["expires_at"] is None

    file_path = users_root / user_id / "memory" / "user_role.md"
    assert "expires_at" not in file_path.read_text(encoding="utf-8")


def test_per_user_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """alice 的 memory 不該被 bob 看到。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key")
    monkeypatch.setenv("ORION_PROVIDER", "anthropic")
    monkeypatch.setenv("ORION_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ORION_DB_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_USERS_DIR", str(tmp_path / "users"))

    with TestClient(create_app()) as client:
        for uname in ("alice", "bob"):
            client.post(
                "/auth/register",
                json={"username": uname, "password": "passw0rd"},
            )
        alice_t = client.post(
            "/auth/login", json={"username": "alice", "password": "passw0rd"},
        ).json()["token"]
        bob_t = client.post(
            "/auth/login", json={"username": "bob", "password": "passw0rd"},
        ).json()["token"]

        client.put(
            "/me/memories/secret.md",
            headers=_h(alice_t),
            json={"name": "alice secret", "description": "private"},
        )
        # bob 看自己 list 應為空
        r_bob = client.get("/me/memories", headers=_h(bob_t)).json()
        assert r_bob == []
        # bob 直打 alice 的檔名也 404(因為他自己沒有)
        r_bob_get = client.get(
            "/me/memories/secret.md", headers=_h(bob_t),
        )
        assert r_bob_get.status_code == 404
