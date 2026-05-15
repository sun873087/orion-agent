"""orion-cowork-sidecar entrypoint。

跑法(僅供開發者調試;production 由 Electron main 啟動):
  uv run --package orion-cowork-sidecar orion-cowork-sidecar
  # 或
  python -m orion_cowork_sidecar
"""

from __future__ import annotations

import asyncio

from .handlers import Handlers
from .rpc import RpcServer


async def _serve() -> None:
    handlers = Handlers()
    server = RpcServer(handlers.methods())
    await server.serve()


def main() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
