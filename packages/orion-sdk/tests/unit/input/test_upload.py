"""upload store — save / read / list / delete + per-user 隔離 + size limit。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_cli.input.upload import (
    UploadNotFoundError,
    UploadTooLargeError,
    delete_upload,
    list_uploads,
    read_upload,
    read_upload_text,
    save_upload,
)


@pytest.fixture(autouse=True)
def _isolate_orion_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path / ".orion"))


def test_save_and_read_bytes() -> None:
    rec = save_upload(user_id="alice", filename="hello.txt", data=b"hello world")
    assert rec.size == 11
    data = read_upload("alice", rec.upload_id)
    assert data == b"hello world"


def test_save_and_read_text() -> None:
    rec = save_upload(user_id="alice", filename="hi.txt", data="日安".encode())
    text = read_upload_text("alice", rec.upload_id)
    assert text == "日安"


def test_user_isolation() -> None:
    rec_a = save_upload(user_id="alice", filename="a.txt", data=b"alice")
    save_upload(user_id="bob", filename="b.txt", data=b"bob")
    # bob 不能讀 alice 的
    with pytest.raises(UploadNotFoundError):
        read_upload("bob", rec_a.upload_id)


def test_size_limit() -> None:
    big = b"x" * 100
    with pytest.raises(UploadTooLargeError):
        save_upload(
            user_id="alice", filename="big.bin", data=big, max_bytes=50,
        )


def test_filename_sanitization() -> None:
    # 試 path traversal — 應只取 basename + 換掉危險字元
    rec = save_upload(user_id="alice", filename="../../etc/passwd", data=b"x")
    assert ".." not in rec.filename
    assert "/" not in rec.filename


def test_delete() -> None:
    rec = save_upload(user_id="alice", filename="x.txt", data=b"x")
    assert delete_upload("alice", rec.upload_id) is True
    with pytest.raises(UploadNotFoundError):
        read_upload("alice", rec.upload_id)


def test_delete_unknown_returns_false() -> None:
    assert delete_upload("alice", "deadbeef") is False


def test_list_uploads() -> None:
    save_upload(user_id="alice", filename="a.txt", data=b"a")
    save_upload(user_id="alice", filename="b.txt", data=b"bb")
    save_upload(user_id="bob", filename="c.txt", data=b"ccc")
    alice = list_uploads("alice")
    assert len(alice) == 2
    bob = list_uploads("bob")
    assert len(bob) == 1


def test_read_invalid_upload_id_format() -> None:
    with pytest.raises(UploadNotFoundError):
        read_upload("alice", "not-hex-format")


def test_no_uploads_dir_returns_empty() -> None:
    assert list_uploads("nonexistent-user") == []


# ─── Phase 19 path migration:legacy fallback ─────────────────────────────────


def test_save_writes_to_new_canonical_path(tmp_path: Path) -> None:
    """新寫一律走 users/<uid>/uploads/,不再走舊頂層 uploads/<uid>/。"""
    rec = save_upload(user_id="alice", filename="x.txt", data=b"x")
    # rec.path 應在 .orion/users/alice/uploads/ 下
    parts = rec.path.parts
    # 找到 ".orion" index,後面該是 users / alice / uploads
    orion_idx = parts.index(".orion")
    assert parts[orion_idx + 1] == "users"
    assert parts[orion_idx + 2] == "alice"
    assert parts[orion_idx + 3] == "uploads"


def _write_legacy(orion_home: Path, user_id: str, upload_id: str, ext: str, data: bytes) -> Path:
    """模擬 Phase 19 之前留下的舊位置檔。"""
    legacy_dir = orion_home / "uploads" / user_id
    legacy_dir.mkdir(parents=True, exist_ok=True)
    p = legacy_dir / f"{upload_id}{ext}"
    p.write_bytes(data)
    return p


def test_read_falls_back_to_legacy_path(tmp_path: Path) -> None:
    """檔案放在舊位置,read_upload 仍要讀得到。"""
    orion_home = tmp_path / ".orion"
    legacy_path = _write_legacy(orion_home, "alice", "deadbeef" * 2, ".txt", b"legacy-data")
    assert legacy_path.exists()
    data = read_upload("alice", "deadbeef" * 2)
    assert data == b"legacy-data"


def test_list_unions_new_and_legacy(tmp_path: Path) -> None:
    """list_uploads 同時看新與舊路徑;同 upload_id 兩處 dedupe(新優先)。"""
    orion_home = tmp_path / ".orion"
    # 舊路徑放 2 個
    _write_legacy(orion_home, "alice", "aaaaaaaa" * 2, ".txt", b"old1")
    _write_legacy(orion_home, "alice", "bbbbbbbb" * 2, ".txt", b"old2")
    # 新路徑(透過 save_upload)放 1 個
    rec_new = save_upload(user_id="alice", filename="new.txt", data=b"new-data")

    recs = list_uploads("alice")
    ids = {r.upload_id for r in recs}
    assert "aaaaaaaa" * 2 in ids
    assert "bbbbbbbb" * 2 in ids
    assert rec_new.upload_id in ids
    assert len(recs) == 3


def test_list_dedup_prefers_new(tmp_path: Path) -> None:
    """同 upload_id 新舊路徑都有 → list 只列新路徑那筆(避免混淆)。"""
    orion_home = tmp_path / ".orion"
    upload_id = "12345678" * 2  # 16 hex
    _write_legacy(orion_home, "alice", upload_id, ".txt", b"old")
    # 直接寫一個同 id 到新路徑(模擬 hash 撞,雖然 uuid 實際不會碰但要鎖行為)
    new_dir = orion_home / "users" / "alice" / "uploads"
    new_dir.mkdir(parents=True, exist_ok=True)
    (new_dir / f"{upload_id}.txt").write_bytes(b"new")

    recs = list_uploads("alice")
    assert len(recs) == 1
    assert recs[0].path.read_bytes() == b"new"


def test_delete_works_on_legacy_path(tmp_path: Path) -> None:
    """legacy 檔可被 delete_upload 刪到。"""
    orion_home = tmp_path / ".orion"
    upload_id = "cafebabe" * 2
    legacy_path = _write_legacy(orion_home, "alice", upload_id, ".txt", b"x")
    assert legacy_path.exists()
    assert delete_upload("alice", upload_id) is True
    assert not legacy_path.exists()


def test_new_path_takes_precedence_in_read(tmp_path: Path) -> None:
    """同 upload_id 兩處都存在 → 讀新的(legacy 不污染)。"""
    orion_home = tmp_path / ".orion"
    upload_id = "feedface" * 2
    _write_legacy(orion_home, "alice", upload_id, ".txt", b"OLD")
    new_dir = orion_home / "users" / "alice" / "uploads"
    new_dir.mkdir(parents=True, exist_ok=True)
    (new_dir / f"{upload_id}.txt").write_bytes(b"NEW")
    assert read_upload("alice", upload_id) == b"NEW"
