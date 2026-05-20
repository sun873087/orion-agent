"""Sandbox 抽象層。

工具(Bash / Write / Edit / Read)透過此抽象層執行,可選不同 backend:
- **LocalBackend**(預設):無隔離,直接走 host(同-6 行為)
- **DockerBackend**:per-session container,隔離 fs / pid / net
- **K8sBackend**:per-session K8s Pod,production-grade 隔離

caller(Conversation / proxy_tools)只看 SandboxBackend Protocol,backend 可換。
"""

from orion_sdk.sandbox.factory import get_sandbox_backend
from orion_sdk.sandbox.local import LocalBackend
from orion_sdk.sandbox.protocol import (
    ExecResult,
    SandboxBackend,
    SandboxError,
)

__all__ = [
    "ExecResult",
    "LocalBackend",
    "SandboxBackend",
    "SandboxError",
    "get_sandbox_backend",
]
