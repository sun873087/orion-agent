"""Phase 31-E:chat-api e2e fixtures。

啟一隻真正的 uvicorn 跑 chat-api,壓力小 + 啟動快用 SQLite in-memory(不依賴
Docker)。

Postgres testcontainer 模式留作 follow-up — 兩者共用同一個 chat_api_server
fixture pattern,只是 db_url 換成 testcontainer 提供。

每個 e2e test:
  - 自動拿到一個 base_url(http://127.0.0.1:<unused-port>)
  - 自動裝 MockProvider,所有 LLM call 都受 fixture 控制(零 token 成本)
  - 帶 fresh SQLite in-memory,test 之間不漏洩

執行:
  cd apps/orion-chat/api && uv run pytest tests/e2e -v -m e2e
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
import uvicorn

from orion_model.provider import set_test_provider_factory


def _find_unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for_port(host: str, port: int, *, timeout: float = 10.0) -> None:
    """Block 直到 port 可連 (server 起來),timeout 後 raise。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            r, w = await asyncio.open_connection(host, port)
            w.close()
            await w.wait_closed()
            return
        except OSError:
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"server on {host}:{port} did not start within {timeout}s")
            await asyncio.sleep(0.05)


@pytest.fixture
def mock_provider_factory(_shared_mock_provider):
    """Test 內可呼叫 factory(turns=[...])一次,後續 get_provider 都回這顆 MockProvider。

    fixture 設計重點:_lifespan cache 的 MockProvider 物件 identity 不變,test 用
    mock_provider_factory 是**重置內部 state**(turns/index/captured_calls),
    不是換新物件。

    用法:
        def test_x(mock_provider_factory):
            mp = mock_provider_factory(turns=[MockTurn(text='hi')])
            ...
    """
    from orion_sdk._testing import MockProvider

    def make(turns: list[Any] | None = None) -> MockProvider:
        _shared_mock_provider.turns = list(turns or [])
        _shared_mock_provider._turn_index = 0
        _shared_mock_provider.captured_calls.clear()
        return _shared_mock_provider

    return make


@pytest.fixture
def _shared_mock_provider():
    """共用 MockProvider 物件 — 整個 e2e test 的生命週期都是同一顆。

    chat_api_server 啟動時 _lifespan 透過 get_provider → set_test_provider_factory
    拿到這顆,並 cache 到 app.state.llm_provider。物件 identity 不變,
    test 透過 mock_provider_factory mutate 內部 state(turns / index)。
    """
    from orion_sdk._testing import MockProvider

    mp = MockProvider(turns=[])
    set_test_provider_factory(lambda name, model: mp)
    yield mp
    set_test_provider_factory(None)


@pytest_asyncio.fixture
async def chat_api_server(monkeypatch, _shared_mock_provider) -> AsyncIterator[dict[str, Any]]:
    """啟一個 ephemeral uvicorn server,fresh SQLite,yield {base_url, port}。

    依賴 _mock_provider_holder 確保 set_test_provider_factory 在 server 啟動前
    就生效(_lifespan 內 _provider_from_env 拿到的是 MockProvider)。
    """
    port = _find_unused_port()

    # Fresh SQLite file (in-memory across processes 不便,用 tmp file)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_url = f"sqlite+aiosqlite:///{tmp.name}"
    monkeypatch.setenv("ORION_DB_URL", db_url)
    monkeypatch.setenv("ORION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ORION_JWT_SECRET", "test-secret-do-not-use-in-prod")

    config = uvicorn.Config(
        "orion_chat_api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        await _wait_for_port("127.0.0.1", port, timeout=10.0)
        yield {"base_url": f"http://127.0.0.1:{port}", "port": port}
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.TimeoutError, Exception):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        Path(tmp.name).unlink(missing_ok=True)


@asynccontextmanager
async def http_client(base_url: str, *, token: str | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """簡便包:httpx AsyncClient 帶 base_url + optional auth。"""
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=10.0) as client:
        yield client
