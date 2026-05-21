"""Cross-pane query callback — 從 handlers.py 內 `_build_ask_pane_callback`
直接 unit-test,不走完整 RPC dispatch。

驗證:
- requester / target 都在同 collab → 回 transcript_excerpt + status
- requester 不在 collab → not_found(防偽造跨 collab query)
- target pane_name 不存在 → not_found
- 自我 query 拒絕(error)
- 沒訊息的 target → status idle / transcript_excerpt 空
- target 有 in-flight ctx → status running
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from orion_cowork_sidecar import storage
from orion_cowork_sidecar.handlers import Handlers


@pytest_asyncio.fixture
async def env() -> AsyncIterator[tuple[Handlers, str, str, str]]:
    """建 collab + 兩個 session_id(@a, @b),回 (handlers, collab_id, sid_a, sid_b)。"""
    with tempfile.TemporaryDirectory(prefix="cowork-askpane-") as d:
        os.environ["ORION_COWORK_DATA_DIR"] = d
        eng = await storage.init_storage()
        coll = await storage.create_collaboration(eng, name="test-collab")
        # 兩個 session — 直接 storage 寫,不過 conversation.create(避免 mcp/provider 依賴)
        await storage.save_session_metadata(
            eng, "sid-a", provider="anthropic", model="claude-haiku-4-5"
        )
        await storage.save_session_metadata(
            eng, "sid-b", provider="anthropic", model="claude-haiku-4-5"
        )
        await storage.add_pane_to_collaboration(
            eng, collaboration_id=coll.id, session_id="sid-a",
            pane_name="@a", pane_role="researcher",
        )
        await storage.add_pane_to_collaboration(
            eng, collaboration_id=coll.id, session_id="sid-b",
            pane_name="@b", pane_role="coder",
        )
        # Handlers 需要 engine 注入 — 給最小化版本
        h = Handlers.__new__(Handlers)
        h._engine = eng # type: ignore[attr-defined]
        h._aborts = {} # type: ignore[attr-defined]
        h._conversations = {} # type: ignore[attr-defined]
        yield h, coll.id, "sid-a", "sid-b"
        await eng.dispose()
        os.environ.pop("ORION_COWORK_DATA_DIR", None)


@pytest.mark.asyncio
async def test_cross_pane_query_same_collab(env):
    h, cid, sid_a, sid_b = env
    cb = h._build_ask_pane_callback(cid, h._engine)
    result = await cb({
        "requesting_session_id": sid_a,
        "pane_name": "@b",
    })
    # B 沒訊息 → idle
    assert result["status"] == "idle"
    assert result["pane_name"] == "@b"
    assert result["pane_role"] == "coder"
    assert result["transcript_excerpt"] == []
    assert result["partial_output"] is None


@pytest.mark.asyncio
async def test_query_target_running(env):
    """target session 在 self._aborts → status running。"""
    h, cid, sid_a, sid_b = env
    # 模擬 target 跑著
    h._aborts[sid_b] = MagicMock()
    cb = h._build_ask_pane_callback(cid, h._engine)
    result = await cb({
        "requesting_session_id": sid_a,
        "pane_name": "@b",
    })
    assert result["status"] == "running"
    assert result["current_action"] is not None


@pytest.mark.asyncio
async def test_query_not_in_collab_rejected(env):
    """requester 不在這個 collab → not_found(防偽造)。"""
    h, cid, sid_a, sid_b = env
    cb = h._build_ask_pane_callback(cid, h._engine)
    result = await cb({
        "requesting_session_id": "outsider-sid",
        "pane_name": "@b",
    })
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_query_target_pane_not_in_collab(env):
    h, cid, sid_a, sid_b = env
    cb = h._build_ask_pane_callback(cid, h._engine)
    result = await cb({
        "requesting_session_id": sid_a,
        "pane_name": "@ghost",
    })
    assert result["status"] == "not_found"
    assert result["pane_name"] == "@ghost"


@pytest.mark.asyncio
async def test_query_self_rejected(env):
    h, cid, sid_a, sid_b = env
    cb = h._build_ask_pane_callback(cid, h._engine)
    result = await cb({
        "requesting_session_id": sid_a,
        "pane_name": "@a", # self
    })
    assert result["status"] == "error"
    assert "yourself" in result["error"]


@pytest.mark.asyncio
async def test_query_with_messages(env):
    """target 有訊息 → transcript_excerpt 非空 + status done。"""
    h, cid, sid_a, sid_b = env
    # 寫幾條 message 進 sid_b
    from orion_model.types import NormalizedMessage
    msgs = [
        NormalizedMessage(role="user", content="design the API"),
        NormalizedMessage(role="assistant",
            content="POST /api/users {name, email}"),
    ]
    await storage.append_messages(h._engine, "sid-b", msgs)
    cb = h._build_ask_pane_callback(cid, h._engine)
    result = await cb({
        "requesting_session_id": sid_a,
        "pane_name": "@b",
    })
    assert result["status"] == "done"
    assert len(result["transcript_excerpt"]) == 2
    assert result["transcript_excerpt"][0]["role"] == "user"
    assert "design" in result["transcript_excerpt"][0]["text"]
    assert result["transcript_excerpt"][1]["role"] == "assistant"
    assert "POST /api/users" in result["transcript_excerpt"][1]["text"]


@pytest.mark.asyncio
async def test_query_running_with_partial_output(env):
    """running + 有訊息(最後一條 assistant)→ partial_output 帶 last assistant text。"""
    h, cid, sid_a, sid_b = env
    from orion_model.types import NormalizedMessage
    msgs = [
        NormalizedMessage(role="user", content="implement X"),
        NormalizedMessage(role="assistant", content="Starting work on X..."),
    ]
    await storage.append_messages(h._engine, "sid-b", msgs)
    h._aborts[sid_b] = MagicMock()
    cb = h._build_ask_pane_callback(cid, h._engine)
    result = await cb({
        "requesting_session_id": sid_a,
        "pane_name": "@b",
    })
    assert result["status"] == "running"
    assert "Starting work on X" in result["partial_output"]
    assert result["current_action"] == "streaming response..."


@pytest.mark.asyncio
async def test_query_n_recent_messages_clamps(env):
    """指定 n_recent_messages → 只回 tail N。"""
    h, cid, sid_a, sid_b = env
    from orion_model.types import NormalizedMessage
    # 10 訊息(交替 user/assistant)
    msgs = [
        NormalizedMessage(
            role="user" if i % 2 == 0 else "assistant",
            content=f"msg-{i}",
        )
        for i in range(10)
    ]
    await storage.append_messages(h._engine, "sid-b", msgs)
    cb = h._build_ask_pane_callback(cid, h._engine)
    result = await cb({
        "requesting_session_id": sid_a,
        "pane_name": "@b",
        "n_recent_messages": 3,
    })
    assert len(result["transcript_excerpt"]) == 3
    # 應該是最後 3 條(msg-7, msg-8, msg-9)
    texts = [e["text"] for e in result["transcript_excerpt"]]
    assert "msg-9" in texts[-1]
