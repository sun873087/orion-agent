"""Multi-pane collaboration storage helpers — unit tests。

涵蓋:
- create / get / list / update / delete collaboration
- add_pane / remove_pane / find_collaboration_pane
- update_pane_position
- get_collaboration_for_session(反查)
- get_collaboration_cost_summary
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from orion_cowork_sidecar import storage


@pytest_asyncio.fixture
async def engine() -> AsyncIterator:
    """Tmp DB,每 test 獨立。"""
    with tempfile.TemporaryDirectory(prefix="cowork-collab-") as d:
        os.environ["ORION_COWORK_DATA_DIR"] = d
        eng = await storage.init_storage()
        yield eng
        await eng.dispose()
        os.environ.pop("ORION_COWORK_DATA_DIR", None)


@pytest.mark.asyncio
async def test_create_get_list_collaboration(engine):
    c = await storage.create_collaboration(
        engine,
        name="feature-x",
        workspace_dir="/tmp/ws",
        project_id=None,
        budget_usd_cap=5.0,
    )
    assert c.id
    assert c.name == "feature-x"
    assert c.workspace_dir == "/tmp/ws"
    assert c.budget_usd_cap == 5.0
    assert c.created_at > 0
    assert c.updated_at >= c.created_at

    got = await storage.get_collaboration(engine, c.id)
    assert got is not None
    assert got.id == c.id

    listing = await storage.list_collaborations(engine)
    assert len(listing) == 1
    assert listing[0].id == c.id


@pytest.mark.asyncio
async def test_get_collaboration_missing(engine):
    got = await storage.get_collaboration(engine, "nonexistent")
    assert got is None


@pytest.mark.asyncio
async def test_update_collaboration(engine):
    c = await storage.create_collaboration(engine, name="orig")
    ok = await storage.update_collaboration(
        engine, c.id, name="renamed", budget_usd_cap=10.0,
    )
    assert ok
    after = await storage.get_collaboration(engine, c.id)
    assert after is not None
    assert after.name == "renamed"
    assert after.budget_usd_cap == 10.0
    assert after.updated_at >= c.updated_at


@pytest.mark.asyncio
async def test_add_pane_to_collaboration(engine):
    c = await storage.create_collaboration(engine, name="collab")
    # Need to first create a session row to FK against — but cowork_session_ext
    # is FK-free (own design),so we can just add ext row directly.
    await storage.add_pane_to_collaboration(
        engine,
        collaboration_id=c.id,
        session_id="sess-A",
        pane_name="@coder",
        pane_role="coder",
        pane_position={"row": 0, "col": 0, "w": 50, "h": 100},
    )
    panes = await storage.list_collaboration_panes(engine, c.id)
    assert len(panes) == 1
    p = panes[0]
    assert p.session_id == "sess-A"
    assert p.pane_name == "@coder"
    assert p.pane_role == "coder"
    assert p.pane_position == {"row": 0, "col": 0, "w": 50, "h": 100}


@pytest.mark.asyncio
async def test_pane_position_persist_json_roundtrip(engine):
    c = await storage.create_collaboration(engine, name="collab")
    pos = {"row": 0, "col": 1, "w": 50, "h": 100, "minimized": False}
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="s1", pane_name="@a",
        pane_position=pos,
    )
    found = await storage.find_collaboration_pane(engine, c.id, "@a")
    assert found is not None
    assert found.pane_position == pos


@pytest.mark.asyncio
async def test_find_collaboration_pane_by_name(engine):
    c = await storage.create_collaboration(engine, name="collab")
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="s1", pane_name="@one",
    )
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="s2", pane_name="@two",
    )
    one = await storage.find_collaboration_pane(engine, c.id, "@one")
    two = await storage.find_collaboration_pane(engine, c.id, "@two")
    missing = await storage.find_collaboration_pane(engine, c.id, "@three")
    assert one is not None and one.session_id == "s1"
    assert two is not None and two.session_id == "s2"
    assert missing is None


@pytest.mark.asyncio
async def test_get_collaboration_for_session(engine):
    c = await storage.create_collaboration(engine, name="collab")
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="sx", pane_name="@x", pane_role="r1",
    )
    cid, name, role = await storage.get_collaboration_for_session(engine, "sx")
    assert cid == c.id
    assert name == "@x"
    assert role == "r1"
    # session 不在 collab → None
    n_cid, n_name, n_role = await storage.get_collaboration_for_session(engine, "other")
    assert n_cid is None and n_name is None and n_role is None


@pytest.mark.asyncio
async def test_remove_pane_from_collaboration(engine):
    c = await storage.create_collaboration(engine, name="collab")
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="sx", pane_name="@x",
    )
    old_cid = await storage.remove_pane_from_collaboration(engine, "sx")
    assert old_cid == c.id
    panes = await storage.list_collaboration_panes(engine, c.id)
    assert panes == []
    # 反查也 None 了
    cid2, _, _ = await storage.get_collaboration_for_session(engine, "sx")
    assert cid2 is None


@pytest.mark.asyncio
async def test_update_pane_position(engine):
    c = await storage.create_collaboration(engine, name="collab")
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="sx", pane_name="@x",
        pane_position={"w": 50},
    )
    ok = await storage.update_pane_position(engine, "sx", {"w": 80, "minimized": True})
    assert ok
    found = await storage.find_collaboration_pane(engine, c.id, "@x")
    assert found is not None
    assert found.pane_position == {"w": 80, "minimized": True}


@pytest.mark.asyncio
async def test_update_pane_position_session_not_in_collab(engine):
    """沒綁 collab 的 session 改 position → no-op,回 False。"""
    ok = await storage.update_pane_position(engine, "no-such-sess", {"w": 50})
    assert ok is False


@pytest.mark.asyncio
async def test_delete_collaboration_releases_panes(engine):
    """刪 collab → 成員 session 的 collaboration_id 變 NULL,session 本身仍可獨立存活。"""
    c = await storage.create_collaboration(engine, name="collab")
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="sx", pane_name="@x",
    )
    ok = await storage.delete_collaboration(engine, c.id)
    assert ok
    # collab 不存在
    assert await storage.get_collaboration(engine, c.id) is None
    # 反查 session — 反查回 None(已釋放)
    cid, name, role = await storage.get_collaboration_for_session(engine, "sx")
    assert cid is None and name is None and role is None


@pytest.mark.asyncio
async def test_add_pane_idempotent_upsert(engine):
    """同 session 重 add 視為改名 / 改 role(upsert)。"""
    c = await storage.create_collaboration(engine, name="collab")
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="sx", pane_name="@orig", pane_role="coder",
    )
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="sx", pane_name="@renamed", pane_role="reviewer",
    )
    panes = await storage.list_collaboration_panes(engine, c.id)
    assert len(panes) == 1
    assert panes[0].pane_name == "@renamed"
    assert panes[0].pane_role == "reviewer"


@pytest.mark.asyncio
async def test_cost_summary_empty_collab(engine):
    c = await storage.create_collaboration(engine, name="empty-collab")
    summary = await storage.get_collaboration_cost_summary(engine, c.id)
    assert summary["total_panes"] == 0
    assert summary["panes"] == []
    assert summary["input_tokens"] == 0
    assert summary["output_tokens"] == 0


@pytest.mark.asyncio
async def test_persist_and_get_session_stats(engine):
    """寫累積 token 用量 → 讀回 → 數字相同。"""
    await storage.persist_session_stats(
        engine, "sx",
        input_tokens=1500, output_tokens=600,
        cache_read_tokens=300, cache_creation_tokens=200, turns=4,
    )
    got = await storage.get_session_stats(engine, "sx")
    assert got["input_tokens"] == 1500
    assert got["output_tokens"] == 600
    assert got["cache_read_tokens"] == 300
    assert got["cache_creation_tokens"] == 200
    assert got["turns"] == 4


@pytest.mark.asyncio
async def test_get_session_stats_missing(engine):
    """沒 row → 全部 0(不是 None)。"""
    got = await storage.get_session_stats(engine, "no-such-sess")
    assert got == {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_creation_tokens": 0, "turns": 0,
    }


@pytest.mark.asyncio
async def test_persist_session_stats_overwrites(engine):
    """重複 persist 覆寫(cumulative 由 caller 傳完整值,不 +=)。"""
    await storage.persist_session_stats(
        engine, "sx",
        input_tokens=100, output_tokens=50, cache_read_tokens=0,
        cache_creation_tokens=0, turns=1,
    )
    await storage.persist_session_stats(
        engine, "sx",
        input_tokens=300, output_tokens=150, cache_read_tokens=20,
        cache_creation_tokens=10, turns=3,
    )
    got = await storage.get_session_stats(engine, "sx")
    assert got["input_tokens"] == 300
    assert got["turns"] == 3


@pytest.mark.asyncio
async def test_cost_summary_with_panes(engine):
    """有 session row(provider/model/tokens 已記)→ summary 加總。"""
    c = await storage.create_collaboration(engine, name="collab-with-data")
    # 建 2 個 session row + 加進 collab
    await storage.save_session_metadata(
        engine, "sess-A",
        provider="anthropic", model="claude-haiku-4-5",
    )
    await storage.save_session_metadata(
        engine, "sess-B",
        provider="openai", model="gpt-4o-mini",
    )
    # token counts 手動寫進 sessions 表(simulate 既有對話的累積)
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            "UPDATE sessions SET input_tokens=1000, output_tokens=500 WHERE id=?",
            ("sess-A",),
        )
        await conn.exec_driver_sql(
            "UPDATE sessions SET input_tokens=2000, output_tokens=800 WHERE id=?",
            ("sess-B",),
        )
        await conn.commit()
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="sess-A", pane_name="@a",
    )
    await storage.add_pane_to_collaboration(
        engine, collaboration_id=c.id, session_id="sess-B", pane_name="@b",
    )
    summary = await storage.get_collaboration_cost_summary(engine, c.id)
    assert summary["total_panes"] == 2
    assert summary["input_tokens"] == 3000
    assert summary["output_tokens"] == 1300
    assert len(summary["panes"]) == 2
    panes_by_name = {p["pane_name"]: p for p in summary["panes"]}
    assert panes_by_name["@a"]["model"] == "claude-haiku-4-5"
    assert panes_by_name["@b"]["model"] == "gpt-4o-mini"
