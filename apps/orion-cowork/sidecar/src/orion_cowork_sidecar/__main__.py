"""orion-cowork-sidecar entrypoint。

跑法(僅供開發者調試;production 由 Electron main 啟動):
  uv run --package orion-cowork-sidecar orion-cowork-sidecar
  # 或
  python -m orion_cowork_sidecar
"""

from __future__ import annotations

import asyncio
import json
import os

# Cowork memory 落獨立 root,跟 CLI / chat-api 的 ~/.orion/users/ 分開。
# 必須在 import orion_sdk.memory.* 之前設,所以放最頂端。
from orion_cowork_sidecar import storage as _cowork_storage

os.environ.setdefault(
    "ORION_USERS_DIR",
    str(_cowork_storage.data_dir() / "users"),
)

from orion_cowork_sidecar.handlers import Handlers  # noqa: E402
from orion_cowork_sidecar.rpc import RpcServer  # noqa: E402


def _install_test_provider_override() -> None:
    """Phase 31-F e2e:ORION_PROVIDER_OVERRIDE=mock → 全 get_provider 回 MockProvider。

    Scripted turns 可由 ORION_MOCK_SCRIPT_JSON env var 傳:
        [{"text": "hi"}, {"text": "second turn"}]
    """
    if os.environ.get("ORION_PROVIDER_OVERRIDE", "").lower() != "mock":
        return
    from orion_model.provider import set_test_provider_factory
    from orion_sdk._testing import MockProvider, MockTurn

    raw = os.environ.get("ORION_MOCK_SCRIPT_JSON", "[]")
    turns: list[MockTurn] = []
    try:
        for t in json.loads(raw):
            if isinstance(t, dict):
                turns.append(MockTurn(text=str(t.get("text", "")), tool_uses=t.get("tool_uses", [])))
    except json.JSONDecodeError:
        pass
    if not turns:
        turns = [MockTurn(text="mocked response")]
    mock = MockProvider(turns=turns)
    set_test_provider_factory(lambda name, model: mock)


async def _serve() -> None:
    _install_test_provider_override()
    handlers = Handlers()
    server = RpcServer(handlers.methods())
    try:
        await server.serve()
    finally:
        await handlers.shutdown()


def main() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
