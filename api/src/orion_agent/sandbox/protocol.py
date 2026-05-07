"""SandboxBackend Protocol 與通用型別。

對應 Phase 7 spec § 5(主文件 + 7b 共用抽象層)。

設計:
- 4 個操作:`exec`、`read_file`、`write_file`、`cleanup`
- 全 async — 配合 anyio / asyncio
- 失敗 raise `SandboxError`(供上層 friendly 訊息)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class SandboxError(RuntimeError):
    """Sandbox 操作失敗(無關 user input,純 backend / infra 問題)。"""


@dataclass
class ExecResult:
    """exec 回傳。"""

    exit_code: int
    stdout: str
    stderr: str = ""
    truncated: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    """backend-specific 額外資訊(container_id / pod_name 等)。"""


@runtime_checkable
class SandboxBackend(Protocol):
    """每 conversation 一個 backend instance(LocalBackend 例外:singleton 也行)。

    Lifecycle:
    - 由 factory / Conversation 建立
    - exec / read_file / write_file 任意呼叫
    - cleanup 結束釋放(DockerBackend 停 container 等)
    """

    name: str
    """backend 名稱:'local' / 'docker' / 'k8s'。"""

    async def exec(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        timeout: float = 30.0,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """跑命令。

        Args:
            argv: argv list,例 `["bash", "-c", "ls"]`
            cwd: working dir,None = backend 預設(host cwd / container /workspace)
            timeout: 秒
            env: 額外 env vars(backend 可選擇 merge or replace)
        """
        ...

    async def read_file(self, path: str) -> bytes:
        """讀 sandbox 內檔案,回 bytes。失敗 raise SandboxError。"""
        ...

    async def write_file(self, path: str, data: bytes) -> None:
        """寫 sandbox 內檔案。父目錄不存在則 raise。"""
        ...

    async def cleanup(self) -> None:
        """釋放 backend 資源(LocalBackend 是 no-op,DockerBackend 停 container)。

        idempotent — 多次 call 不該錯。
        """
        ...
