"""sandbox backend factory。

對應 spec § 5 backend 選擇邏輯。

選 backend 順序:
1. CLI / API 顯式傳 name(`get_sandbox_backend("docker")`)
2. env `ORION_SANDBOX`(local / docker)
3. 預設 `local`
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from orion_agent.sandbox.local import LocalBackend
from orion_agent.sandbox.protocol import SandboxBackend, SandboxError

if TYPE_CHECKING:
    pass


def get_sandbox_backend(name: str | None = None, **kwargs: object) -> SandboxBackend:
    """取得 backend instance。

    Args:
        name: 指定 backend 名稱(local / docker)。None → 讀環境變數 / 預設 local
        **kwargs: backend 特定參數(image / container_name 等),傳給該 backend 建構

    Raises:
        SandboxError:unknown backend / 該 backend 套件未裝
    """
    effective = name or os.environ.get("ORION_SANDBOX", "local")
    effective = effective.lower().strip()

    if effective == "local":
        return LocalBackend()

    if effective == "docker":
        from orion_agent.sandbox.docker_backend import DockerBackend

        return DockerBackend(**kwargs)  # type: ignore[arg-type]

    raise SandboxError(f"unknown sandbox backend: {effective!r}")
