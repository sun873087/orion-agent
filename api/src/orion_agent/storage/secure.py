"""SecureStorage — 加密儲存敏感資料(token / API key 等)。Phase 14。

對應 TS Claude Code `src/utils/secureStorage/`。

Backend 優先序(由 `create_backend()` 自動選):
  1. **OS keychain**(macOS Keychain / Linux Secret Service / Windows Credential Manager)
     — 用 `keyring` 套件;dev 機器最佳體驗(免管 master key)
  2. **加密 file**(`cryptography.fernet`)— fallback;docker / sandbox / CI 環境
     沒 keychain 時用,master key 從 env `ORION_MASTER_KEY` 或 `~/.orion/.master.key`
     (mode 600)讀

未來 phase(production SaaS)可加 SecretsManagerBackend(AWS / Vault / GCP)— 同
SecureStorageBackend Protocol,呼叫端不變。Phase 14 範圍只到 Keychain + EncryptedFile,
production cloud 留新 phase plan(`docs/phases/23-cloud-secrets.md` 視需求開)。

Sync vs async:既有用法都 async(統一 await pattern);實際 keyring / fernet 都是
同步操作,內部用 sync,僅在介面層 wrap 為 async def。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_DEFAULT_SERVICE = "orion-agent"
_DEFAULT_SECRETS_FILE = "secrets.enc"
_DEFAULT_MASTER_KEY_FILE = ".master.key"


class SecureStorageBackend(Protocol):
    """敏感資料 backend 介面。"""

    async def get(self, key: str) -> str | None:
        """讀取;不存在回 None,不 raise。"""
        ...

    async def set(self, key: str, value: str) -> None:
        """寫入(覆蓋既有);失敗 raise。"""
        ...

    async def delete(self, key: str) -> None:
        """刪除;不存在 silently no-op。"""
        ...

    async def list_keys(self) -> list[str]:
        """列出所有 key(供 audit / debug)。"""
        ...


# ─── Keychain backend ───────────────────────────────────────────────────────


class KeychainBackend:
    """OS keychain backend(macOS / Linux Secret Service / Windows Credential Manager)。

    用 `keyring` 套件做跨平台 wrapper。每筆儲存:
        keyring.set_password(service=ORION_KEYCHAIN_SERVICE, username=key, password=value)

    `list_keys` keyring 沒提供 — 我們在 keychain 內額外存一筆 `__index__`(JSON 陣列)
    手動維護(spec 沒要求嚴格 enumerate,本實作為 best-effort)。
    """

    _INDEX_KEY = "__index__"

    def __init__(self, service: str | None = None) -> None:
        self.service = service or os.environ.get(
            "ORION_KEYCHAIN_SERVICE", _DEFAULT_SERVICE,
        )

    def _keyring(self) -> Any:
        """import keyring lazily;`Any` 因為 keyring 無 type stub。"""
        import keyring
        return keyring

    async def get(self, key: str) -> str | None:
        kr = self._keyring()
        try:
            result = kr.get_password(self.service, key)
        except Exception as e:  # noqa: BLE001 — backend init may fail
            logger.warning("keychain get failed for %s: %s", key, e)
            return None
        return result if isinstance(result, str) else None

    async def set(self, key: str, value: str) -> None:
        kr = self._keyring()
        kr.set_password(self.service, key, value)
        await self._add_to_index(key)

    async def delete(self, key: str) -> None:
        kr = self._keyring()
        try:
            kr.delete_password(self.service, key)
        except Exception as e:  # noqa: BLE001 — keyring 各 backend 不同 exception
            # 不存在 / delete 失敗都吞;list_keys 仍會更新 index
            logger.debug("keychain delete %s: %s", key, e)
        await self._remove_from_index(key)

    async def list_keys(self) -> list[str]:
        index_raw = await self.get(self._INDEX_KEY)
        if not index_raw:
            return []
        try:
            keys = json.loads(index_raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(keys, list):
            return []
        return [k for k in keys if isinstance(k, str) and k != self._INDEX_KEY]

    async def _add_to_index(self, key: str) -> None:
        if key == self._INDEX_KEY:
            return
        existing = await self.list_keys()
        if key in existing:
            return
        existing.append(key)
        kr = self._keyring()
        kr.set_password(self.service, self._INDEX_KEY, json.dumps(existing))

    async def _remove_from_index(self, key: str) -> None:
        existing = await self.list_keys()
        if key not in existing:
            return
        existing.remove(key)
        kr = self._keyring()
        kr.set_password(self.service, self._INDEX_KEY, json.dumps(existing))


# ─── EncryptedFile backend ──────────────────────────────────────────────────


class EncryptedFileBackend:
    """fallback backend:fernet 對稱加密,所有 key 存單一 JSON。

    Master key 來源優先序:
      1. `ORION_MASTER_KEY` env(base64 fernet key)
      2. `<file_dir>/.master.key`(mode 600)— 不存在自動產生
    """

    def __init__(
        self,
        file_path: Path | None = None,
        *,
        master_key: bytes | None = None,
    ) -> None:
        if file_path is None:
            base = os.environ.get("ORION_HOME") or str(Path.home() / ".orion")
            file_path = Path(base) / _DEFAULT_SECRETS_FILE
        self.file_path = file_path
        self._fernet = Fernet(master_key or self._load_or_create_master_key())

    def _load_or_create_master_key(self) -> bytes:
        env_key = os.environ.get("ORION_MASTER_KEY")
        if env_key:
            return env_key.encode()

        key_file = self.file_path.parent / _DEFAULT_MASTER_KEY_FILE
        if key_file.exists():
            try:
                return key_file.read_bytes()
            except OSError as e:
                logger.warning(
                    "master key file %s unreadable (%s) — generating new",
                    key_file, e,
                )

        new_key = Fernet.generate_key()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(new_key)
        # Windows / 沒 chmod 權限的 fs:silently 略
        with contextlib.suppress(OSError):
            os.chmod(key_file, 0o600)
        return new_key

    def _read_all(self) -> dict[str, str]:
        if not self.file_path.exists():
            return {}
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}

    def _write_all(self, data: dict[str, str]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file_path.with_suffix(self.file_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.file_path)
        with contextlib.suppress(OSError):
            os.chmod(self.file_path, 0o600)

    async def get(self, key: str) -> str | None:
        data = self._read_all()
        encrypted = data.get(key)
        if encrypted is None:
            return None
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except InvalidToken:
            logger.warning("decrypt failed for key %s — master key changed?", key)
            return None

    async def set(self, key: str, value: str) -> None:
        data = self._read_all()
        data[key] = self._fernet.encrypt(value.encode()).decode()
        self._write_all(data)

    async def delete(self, key: str) -> None:
        data = self._read_all()
        if key in data:
            del data[key]
            self._write_all(data)

    async def list_keys(self) -> list[str]:
        return sorted(self._read_all().keys())


# ─── Factory ────────────────────────────────────────────────────────────────


def create_backend(
    *,
    force_file: bool = False,
    file_path: Path | None = None,
) -> SecureStorageBackend:
    """根據環境選 backend。

    Args:
        force_file: True → 一律走 EncryptedFileBackend(測試 / docker 用)。
            等同 env `ORION_DISABLE_KEYCHAIN=1`。
        file_path: file backend 的存放位置(預設 `$ORION_HOME/secrets.enc`)。

    Selection:
        force_file=True 或 env `ORION_DISABLE_KEYCHAIN=1` → EncryptedFileBackend
        否則嘗試 KeychainBackend(import keyring + sanity probe);失敗 →
        EncryptedFileBackend
    """
    if force_file or os.environ.get("ORION_DISABLE_KEYCHAIN") == "1":
        return EncryptedFileBackend(file_path)

    try:
        # sanity probe:確認 keyring 套件 + 至少有個 backend 可用
        import keyring
        # get_keyring 回 backend instance,本身不會 raise — 但若整個 import 失敗
        # 以下還是會走 except
        _ = keyring.get_keyring()
        return KeychainBackend()
    except Exception as e:  # noqa: BLE001
        logger.info(
            "keyring unavailable (%s) — falling back to encrypted file", e,
        )
        return EncryptedFileBackend(file_path)


__all__ = [
    "EncryptedFileBackend",
    "KeychainBackend",
    "SecureStorageBackend",
    "create_backend",
]
