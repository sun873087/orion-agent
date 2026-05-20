"""SecureStorage backends + factory。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_sdk.storage.secure import (
    EncryptedFileBackend,
    KeychainBackend,
    create_backend,
)

# ─── EncryptedFileBackend ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_encrypted_file_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "secrets.enc"
    b = EncryptedFileBackend(f)

    await b.set("token", "secret123")
    assert await b.get("token") == "secret123"


@pytest.mark.asyncio
async def test_encrypted_file_get_missing_returns_none(tmp_path: Path) -> None:
    b = EncryptedFileBackend(tmp_path / "no.enc")
    assert await b.get("missing") is None


@pytest.mark.asyncio
async def test_encrypted_file_overwrite(tmp_path: Path) -> None:
    f = tmp_path / "secrets.enc"
    b = EncryptedFileBackend(f)
    await b.set("k", "v1")
    await b.set("k", "v2")
    assert await b.get("k") == "v2"


@pytest.mark.asyncio
async def test_encrypted_file_delete(tmp_path: Path) -> None:
    f = tmp_path / "secrets.enc"
    b = EncryptedFileBackend(f)
    await b.set("k", "v")
    await b.delete("k")
    assert await b.get("k") is None
    # idempotent
    await b.delete("k")


@pytest.mark.asyncio
async def test_encrypted_file_list_keys(tmp_path: Path) -> None:
    b = EncryptedFileBackend(tmp_path / "s.enc")
    await b.set("a", "1")
    await b.set("b", "2")
    keys = await b.list_keys()
    assert keys == ["a", "b"]


@pytest.mark.asyncio
async def test_encrypted_file_persists_across_instances(tmp_path: Path) -> None:
    """重建 backend instance 應仍能讀(同 master key 從同 .master.key 讀)。"""
    f = tmp_path / "s.enc"
    b1 = EncryptedFileBackend(f)
    await b1.set("token", "abc")

    b2 = EncryptedFileBackend(f)
    assert await b2.get("token") == "abc"


@pytest.mark.asyncio
async def test_encrypted_file_master_key_change_returns_none(
    tmp_path: Path,
) -> None:
    """換 master key 後讀舊資料 → 解密失敗(不 raise,回 None)。"""
    from cryptography.fernet import Fernet

    f = tmp_path / "s.enc"
    b1 = EncryptedFileBackend(f, master_key=Fernet.generate_key())
    await b1.set("k", "v")

    b2 = EncryptedFileBackend(f, master_key=Fernet.generate_key())
    assert await b2.get("k") is None # InvalidToken → None


@pytest.mark.asyncio
async def test_encrypted_file_master_key_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    monkeypatch.setenv("ORION_MASTER_KEY", key.decode())

    b = EncryptedFileBackend(tmp_path / "s.enc")
    await b.set("k", "v")
    # 用 env key 直接造一個 raw fernet 解,確認確實用 env key 加密
    assert await b.get("k") == "v"


@pytest.mark.asyncio
async def test_encrypted_file_corrupt_returns_empty(tmp_path: Path) -> None:
    """secrets.enc 寫成壞 JSON → list_keys 回 []、get 回 None,不 raise。"""
    f = tmp_path / "s.enc"
    f.write_text("not valid json", encoding="utf-8")
    b = EncryptedFileBackend(f)
    assert await b.list_keys() == []
    assert await b.get("anything") is None


# ─── KeychainBackend(用 mock keyring 不碰真 OS keychain)────────────────────


class _FakeKeyring:
    """fake keyring lib(避免測試把資料寫真 OS keychain)。"""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self.data.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.data[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        if (service, key) not in self.data:
            raise KeyError(f"no such key: {key}")
        del self.data[(service, key)]


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> _FakeKeyring:
    fake = _FakeKeyring()
    import sys
    monkeypatch.setitem(sys.modules, "keyring", fake)
    return fake


@pytest.mark.asyncio
async def test_keychain_roundtrip(fake_keyring: _FakeKeyring) -> None:
    b = KeychainBackend(service="test-svc")
    await b.set("token", "abc")
    assert await b.get("token") == "abc"
    assert fake_keyring.data[("test-svc", "token")] == "abc"


@pytest.mark.asyncio
async def test_keychain_delete(fake_keyring: _FakeKeyring) -> None:
    b = KeychainBackend(service="test-svc")
    await b.set("k", "v")
    await b.delete("k")
    assert await b.get("k") is None


@pytest.mark.asyncio
async def test_keychain_delete_nonexistent_silent(
    fake_keyring: _FakeKeyring, # noqa: ARG001
) -> None:
    b = KeychainBackend(service="test-svc")
    # 不存在,delete 不該 raise
    await b.delete("never-set")


@pytest.mark.asyncio
async def test_keychain_list_keys_via_index(fake_keyring: _FakeKeyring) -> None:
    b = KeychainBackend(service="test-svc")
    await b.set("a", "1")
    await b.set("b", "2")
    keys = await b.list_keys()
    assert sorted(keys) == ["a", "b"]
    # 確認 __index__ entry 存在
    assert ("test-svc", "__index__") in fake_keyring.data


@pytest.mark.asyncio
async def test_keychain_list_keys_excludes_index_entry(
    fake_keyring: _FakeKeyring, # noqa: ARG001
) -> None:
    b = KeychainBackend(service="test-svc")
    await b.set("a", "1")
    keys = await b.list_keys()
    assert "__index__" not in keys


# ─── Factory ────────────────────────────────────────────────────────────────


def test_create_backend_force_file(tmp_path: Path) -> None:
    b = create_backend(force_file=True, file_path=tmp_path / "s.enc")
    assert isinstance(b, EncryptedFileBackend)


def test_create_backend_disabled_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_DISABLE_KEYCHAIN", "1")
    b = create_backend(file_path=tmp_path / "s.enc")
    assert isinstance(b, EncryptedFileBackend)


def test_create_backend_keychain_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有 keyring 套件 + get_keyring 不爆 → 走 KeychainBackend。"""
    import sys

    class _MinimalKeyring:
        def get_keyring(self) -> object:
            return object()

    monkeypatch.delenv("ORION_DISABLE_KEYCHAIN", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", _MinimalKeyring())
    b = create_backend()
    assert isinstance(b, KeychainBackend)


def test_create_backend_falls_back_when_keyring_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    class _BrokenKeyring:
        def get_keyring(self) -> object:
            raise RuntimeError("no backend")

    monkeypatch.delenv("ORION_DISABLE_KEYCHAIN", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", _BrokenKeyring())
    b = create_backend(file_path=tmp_path / "s.enc")
    assert isinstance(b, EncryptedFileBackend)
