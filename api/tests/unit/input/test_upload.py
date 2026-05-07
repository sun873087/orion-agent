"""upload store — save / read / list / delete + per-user 隔離 + size limit。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.input.upload import (
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
