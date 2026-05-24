"""Multi-pane DispatchPane — storage + callback unit tests。

涵蓋:
- Storage:enqueue / list_pending / mark_fired / mark_rejected / count
- Opt-out pref CRUD
- Streaming flag in-memory state(mark / is)
- DispatchPane callback:
  - empty params → error
  - target pane 不在 collab → not_found
  - self-dispatch → rejected
  - loop detection(target 在 chain 內)→ rejected
  - max depth(10)→ rejected
  - target opt-out → rejected
  - idle target → fired + queue 有 1 筆 pending
  - busy target → queued + queue position 對
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from orion_cowork_sidecar import storage
from orion_cowork_sidecar.dispatch_tools import (
    DispatchPaneInput,
    DispatchPaneTool,
)
from orion_cowork_sidecar.handlers import Handlers
from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent


# ─── Fixtures ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def env() -> AsyncIterator[tuple[Handlers, str, str, str]]:
    """建 collab + 兩個 pane(@a, @b),回 (handlers, collab_id, sid_a, sid_b)。"""
    with tempfile.TemporaryDirectory(prefix="cowork-dispatch-") as d:
        os.environ["ORION_COWORK_DATA_DIR"] = d
        eng = await storage.init_storage()
        coll = await storage.create_collaboration(eng, name="dispatch-test")
        await storage.save_session_metadata(
            eng, "sid-a", provider="anthropic", model="claude-haiku-4-5",
        )
        await storage.save_session_metadata(
            eng, "sid-b", provider="anthropic", model="claude-haiku-4-5",
        )
        await storage.add_pane_to_collaboration(
            eng, collaboration_id=coll.id, session_id="sid-a",
            pane_name="@a", pane_role="researcher",
        )
        await storage.add_pane_to_collaboration(
            eng, collaboration_id=coll.id, session_id="sid-b",
            pane_name="@b", pane_role="coder",
        )
        h = Handlers.__new__(Handlers)
        h._engine = eng # type: ignore[attr-defined]
        h._aborts = {} # type: ignore[attr-defined]
        h._conversations = {} # type: ignore[attr-defined]
        h._active_turn_chains = {} # type: ignore[attr-defined]
        h._dispatch_draining = set() # type: ignore[attr-defined]
        h._bg_tasks = set() # type: ignore[attr-defined]
        # 清 module-level streaming flag(其他 test 殘留可能影響)
        storage._active_streaming_sessions.clear()
        yield h, coll.id, "sid-a", "sid-b"
        await eng.dispose()
        os.environ.pop("ORION_COWORK_DATA_DIR", None)
        storage._active_streaming_sessions.clear()


# ─── Storage layer ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_and_list_pending(env) -> None:
    h, cid, sid_a, sid_b = env
    did = await storage.enqueue_dispatch(
        h._engine, target_session_id=sid_b, from_pane="@a",
        prompt="do something", chain_path=["@a"],
    )
    pending = await storage.list_pending_dispatch(h._engine, sid_b)
    assert len(pending) == 1
    assert pending[0]["id"] == did
    assert pending[0]["prompt"] == "do something"
    assert pending[0]["from_pane"] == "@a"
    assert pending[0]["chain_path"] == ["@a"]


@pytest.mark.asyncio
async def test_mark_fired_removes_from_pending(env) -> None:
    h, cid, sid_a, sid_b = env
    did = await storage.enqueue_dispatch(
        h._engine, target_session_id=sid_b, from_pane="@a",
        prompt="x", chain_path=[],
    )
    assert await storage.count_pending_dispatch(h._engine, sid_b) == 1
    await storage.mark_dispatch_fired(h._engine, did)
    assert await storage.count_pending_dispatch(h._engine, sid_b) == 0


@pytest.mark.asyncio
async def test_mark_rejected_with_error(env) -> None:
    h, _, _, sid_b = env
    did = await storage.enqueue_dispatch(
        h._engine, target_session_id=sid_b, from_pane="@a",
        prompt="x", chain_path=[],
    )
    await storage.mark_dispatch_rejected(h._engine, did, "test error reason")
    # status='rejected' → 不在 pending
    assert await storage.count_pending_dispatch(h._engine, sid_b) == 0


@pytest.mark.asyncio
async def test_streaming_flag(env) -> None:
    """mark_session_streaming / is_session_streaming in-memory state。"""
    _, _, sid_a, sid_b = env
    assert storage.is_session_streaming(sid_b) is False
    storage.mark_session_streaming(sid_b, True)
    assert storage.is_session_streaming(sid_b) is True
    assert storage.is_session_streaming(sid_a) is False # 另一 session 不受影響
    storage.mark_session_streaming(sid_b, False)
    assert storage.is_session_streaming(sid_b) is False


# ─── Opt-out pref ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_opt_out_crud(env) -> None:
    h, _, _, _ = env
    assert await storage.get_dispatch_disabled_panes(h._engine) == set()
    assert await storage.is_pane_dispatch_disabled(h._engine, "@b") is False
    await storage.set_dispatch_disabled_panes(h._engine, {"@b", "@reviewer"})
    assert await storage.get_dispatch_disabled_panes(h._engine) == {"@b", "@reviewer"}
    assert await storage.is_pane_dispatch_disabled(h._engine, "@b") is True
    assert await storage.is_pane_dispatch_disabled(h._engine, "@frontend") is False
    # Empty set 視為清空
    await storage.set_dispatch_disabled_panes(h._engine, set())
    assert await storage.get_dispatch_disabled_panes(h._engine) == set()


# ─── DispatchPaneTool input validation ───────────────────────


@pytest.mark.asyncio
async def test_tool_empty_pane_name_errors() -> None:
    async def cb(_p):  # never reached
        return {}
    tool = DispatchPaneTool(callback=cb)
    events = []
    async for ev in tool.call(
        DispatchPaneInput(pane_name="", prompt="x"), AgentContext(),
    ):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "pane_name" in events[0].message


@pytest.mark.asyncio
async def test_tool_empty_prompt_errors() -> None:
    async def cb(_p):
        return {}
    tool = DispatchPaneTool(callback=cb)
    events = []
    async for ev in tool.call(
        DispatchPaneInput(pane_name="@b", prompt="   "), AgentContext(),
    ):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "prompt" in events[0].message


# ─── Dispatch callback (chain / opt-out / fire / queue) ─────


@pytest.mark.asyncio
async def test_callback_target_not_found(env) -> None:
    h, cid, sid_a, _ = env
    cb = h._build_dispatch_callback(
        collaboration_id=cid,
        current_session_id=sid_a,
        current_pane_name="@a",
        engine=h._engine,
    )
    r = await cb({"pane_name": "@nonexistent", "prompt": "x"})
    assert r["status"] == "not_found"


@pytest.mark.asyncio
async def test_callback_self_dispatch_rejected(env) -> None:
    h, cid, sid_a, _ = env
    cb = h._build_dispatch_callback(
        collaboration_id=cid,
        current_session_id=sid_a,
        current_pane_name="@a",
        engine=h._engine,
    )
    r = await cb({"pane_name": "@a", "prompt": "x"})
    assert r["status"] == "rejected"
    assert "yourself" in r["error"]


@pytest.mark.asyncio
async def test_callback_loop_detection(env) -> None:
    """A 在 chain 內,B 想再 dispatch 給 A → reject。"""
    h, cid, sid_a, sid_b = env
    # 模擬 B 的 turn 由 A dispatch 觸發,chain=[@a]
    h._active_turn_chains[sid_b] = ["@a"]
    cb = h._build_dispatch_callback(
        collaboration_id=cid,
        current_session_id=sid_b,
        current_pane_name="@b",
        engine=h._engine,
    )
    r = await cb({"pane_name": "@a", "prompt": "ping back"})
    assert r["status"] == "rejected"
    assert "loop" in r["error"]
    assert r["chain_path"] == ["@a", "@b"]


@pytest.mark.asyncio
async def test_callback_max_depth_rejected(env) -> None:
    """chain 已 9 個 pane,加 @a 就 10 → 還可;但要 dispatch 給 @b 算 11(next_chain len=10)會 reject。"""
    h, cid, sid_a, sid_b = env
    # 注 9 個假 pane 進 chain;@a 加上去就是第 10 個。
    h._active_turn_chains[sid_a] = [f"@p{i}" for i in range(9)]
    cb = h._build_dispatch_callback(
        collaboration_id=cid,
        current_session_id=sid_a,
        current_pane_name="@a",
        engine=h._engine,
    )
    r = await cb({"pane_name": "@b", "prompt": "deep call"})
    assert r["status"] == "rejected"
    assert "max" in r["error"].lower() or "depth" in r["error"].lower()


@pytest.mark.asyncio
async def test_callback_opt_out_rejected(env) -> None:
    h, cid, sid_a, _ = env
    await storage.set_dispatch_disabled_panes(h._engine, {"@b"})
    cb = h._build_dispatch_callback(
        collaboration_id=cid,
        current_session_id=sid_a,
        current_pane_name="@a",
        engine=h._engine,
    )
    r = await cb({"pane_name": "@b", "prompt": "x"})
    assert r["status"] == "rejected"
    assert "opted out" in r["error"]


@pytest.mark.asyncio
async def test_callback_fires_when_idle(env, monkeypatch) -> None:
    """target idle → enqueue + spawn drain task。為了不真 spawn,monkeypatch
    _spawn_dispatch_drain 改成記下被呼。"""
    h, cid, sid_a, sid_b = env
    spawned: list[str] = []
    monkeypatch.setattr(
        h, "_spawn_dispatch_drain", lambda tsid: spawned.append(tsid),
    )
    cb = h._build_dispatch_callback(
        collaboration_id=cid,
        current_session_id=sid_a,
        current_pane_name="@a",
        engine=h._engine,
    )
    r = await cb({"pane_name": "@b", "prompt": "tell a joke"})
    assert r["status"] == "fired"
    assert r["target_pane"] == "@b"
    assert r["chain_path"] == ["@a"]
    assert spawned == [sid_b]
    # Pending row 應該有 1 筆
    assert await storage.count_pending_dispatch(h._engine, sid_b) == 1


@pytest.mark.asyncio
async def test_callback_queues_when_busy(env, monkeypatch) -> None:
    """target streaming → enqueue but 不 spawn drain(等 target turn 結束 drain)。"""
    h, cid, sid_a, sid_b = env
    storage.mark_session_streaming(sid_b, True)
    spawned: list[str] = []
    monkeypatch.setattr(
        h, "_spawn_dispatch_drain", lambda tsid: spawned.append(tsid),
    )
    cb = h._build_dispatch_callback(
        collaboration_id=cid,
        current_session_id=sid_a,
        current_pane_name="@a",
        engine=h._engine,
    )
    r1 = await cb({"pane_name": "@b", "prompt": "task 1"})
    assert r1["status"] == "queued"
    assert r1["queue_position"] == 1
    r2 = await cb({"pane_name": "@b", "prompt": "task 2"})
    assert r2["status"] == "queued"
    assert r2["queue_position"] == 2
    # 沒 spawn(target busy → 等 turn-end hook drain)
    assert spawned == []


@pytest.mark.asyncio
async def test_tag_latest_user_message_meta(env) -> None:
    """tag_latest_user_message_meta 找到含 <from-pane 的 user msg 更新 meta。"""
    h, _, _, sid_b = env
    # 插一筆 user message(含 <from-pane>)+ 一筆普通 user message — 應該 tag 含 from-pane 那筆
    from orion_sdk.storage.db.engine import db_session
    from orion_sdk.storage.db.models import Message as MR
    async with db_session(h._engine) as s:
        s.add(MR(
            id="m1", session_id=sid_b, role="user",
            content_json="<from-pane name=\"@a\">hi</from-pane>",
            raw_text="<from-pane name=\"@a\">hi</from-pane>",
        ))
        await s.commit()
    ok = await storage.tag_latest_user_message_meta(
        h._engine, sid_b, {"from_pane": "@a", "chain_path": ["@a"]},
    )
    assert ok is True
    # 驗證 meta 寫進去了
    rows = await storage.load_raw_messages(h._engine, sid_b)
    assert len(rows) == 1
    _id, _role, _content, meta = rows[0]
    assert isinstance(meta, dict)
    assert meta.get("from_pane") == "@a"
