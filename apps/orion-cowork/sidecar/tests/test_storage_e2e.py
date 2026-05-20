"""D:Cowork SQLite persistence cross-restart 驗證。

不需要真 LLM:用 sub-process spawn sidecar → 注 stdin / 讀 stdout 驗證
list / delete 跨 process 都對。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def _run_sidecar(input_lines: list[str], data_dir: str, timeout: float = 15.0) -> list[dict]:
    """Spawn sidecar 一次,送 input,等 EOF/結束,回 parsed frames。"""
    env = dict(os.environ)
    env["ORION_COWORK_DATA_DIR"] = data_dir
    proc = subprocess.run(
        [sys.executable, "-m", "orion_cowork_sidecar"],
        input="\n".join(input_lines) + "\n",
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return [json.loads(line) for line in proc.stdout.strip().split("\n") if line]


@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory(prefix="cowork-e2e-") as d:
        yield d


def test_conversation_persists_across_process_restart(data_dir: str) -> None:
    """Process A 建對話 → 結束 → Process B 列出該對話。"""
    # A:create
    frames_a = _run_sidecar([
        '{"id":"a","method":"conversation.create","params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
    ], data_dir)
    created = next(f for f in frames_a if f.get("id") == "a")
    assert created["event"] == "conversation_created"
    sid = created["data"]["session_id"]
    assert sid

    # B:fresh process,list
    frames_b = _run_sidecar([
        '{"id":"b","method":"conversation.list"}',
    ], data_dir)
    listed = next(f for f in frames_b if f.get("id") == "b")
    assert listed["event"] == "conversation_list"
    sessions = listed["data"]["sessions"]
    assert any(s["session_id"] == sid for s in sessions)
    assert any(s["provider"] == "anthropic" for s in sessions)


@pytest.mark.asyncio
async def test_delete_session_cascades_loop_schedules(data_dir: str) -> None:
    """刪 session 時,綁該 session 的 Loop 排程一起刪;純 Schedule 不動。"""
    os.environ["ORION_COWORK_DATA_DIR"] = data_dir
    from orion_cowork_sidecar import storage

    engine = await storage.init_storage()
    # 建兩個 session
    sid_with_loop = "11111111-1111-1111-1111-111111111111"
    sid_keep = "22222222-2222-2222-2222-222222222222"
    await storage.save_session_metadata(
        engine, sid_with_loop, provider="anthropic", model="claude-haiku-4-5",
    )
    await storage.save_session_metadata(
        engine, sid_keep, provider="anthropic", model="claude-haiku-4-5",
    )
    # 一筆 Loop 綁 sid_with_loop;一筆獨立 Schedule(target_session_id NULL)
    loop = await storage.create_schedule(
        engine, name="hi loop", cron_expr="* * * * *",
        trigger_type="prompt", payload="ping",
        target_session_id=sid_with_loop,
    )
    sched = await storage.create_schedule(
        engine, name="daily news", cron_expr="0 8 * * *",
        trigger_type="prompt", payload="news",
    )
    # 刪 sid_with_loop → loop 排程消失,但獨立 sched 仍在
    assert await storage.delete_session(engine, sid_with_loop) is True
    after = await storage.list_schedules(engine)
    after_ids = {s.id for s in after}
    assert loop.id not in after_ids, "Loop 綁該 session,應該 cascade delete"
    assert sched.id in after_ids, "純 Schedule 不該被牽連"
    # sid_keep 也還在
    listed = await storage.list_sessions(engine)
    assert any(s.session_id == sid_keep for s in listed)
    await engine.dispose()


@pytest.mark.asyncio
async def test_fork_session_copies_messages_and_lineage(data_dir: str) -> None:
    """fork_session 複製 [0..N] messages 到新 session,標 forked_from_* 系譜,
    workspace/project 繼承,原 session 完全不動。"""
    os.environ["ORION_COWORK_DATA_DIR"] = data_dir
    from orion_model.types import NormalizedMessage
    from orion_cowork_sidecar import storage

    engine = await storage.init_storage()
    src_sid = "33333333-3333-3333-3333-333333333333"
    await storage.save_session_metadata(
        engine, src_sid, provider="anthropic", model="claude-haiku-4-5",
    )
    await storage.set_session_workspace(engine, src_sid, "/tmp/ws-fork")
    # 塞 4 筆訊息
    await storage.append_messages(engine, src_sid, [
        NormalizedMessage(role="user", content="Q1"),
        NormalizedMessage(role="assistant", content="A1"),
        NormalizedMessage(role="user", content="Q2"),
        NormalizedMessage(role="assistant", content="A2"),
    ])
    # Fork up_to_index=1(inclusive)→ 新 session 應該只有 Q1 + A1
    new_sid = await storage.fork_session(
        engine,
        source_session_id=src_sid,
        up_to_message_index=1,
        title="探索方案 A",
    )
    # 新 session 訊息正確
    new_msgs = await storage.load_messages(engine, new_sid)
    assert len(new_msgs) == 2
    assert new_msgs[0].content == "Q1"
    assert new_msgs[1].content == "A1"
    # 原 session 不動
    src_msgs = await storage.load_messages(engine, src_sid)
    assert len(src_msgs) == 4
    # 系譜 + workspace 繼承
    lineage = await storage.get_session_fork_lineage(engine, new_sid)
    assert lineage == {
        "forked_from_session_id": src_sid,
        "forked_from_message_index": 1,
    }
    ext = await storage.get_session_ext(engine, new_sid)
    assert ext["workspace_dir"] == "/tmp/ws-fork"
    # Bad index → ValueError
    with pytest.raises(ValueError):
        await storage.fork_session(
            engine, source_session_id=src_sid, up_to_message_index=99,
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_many_sessions_bulk(data_dir: str) -> None:
    """Bulk delete:傳一組 sids,各自跑 cascade(含 fork 子孫);無關 session 不動。"""
    os.environ["ORION_COWORK_DATA_DIR"] = data_dir
    from orion_cowork_sidecar import storage

    engine = await storage.init_storage()
    keep_sid = "66666666-6666-6666-6666-666666666666"
    drop1 = "77777777-7777-7777-7777-777777777777"
    drop2 = "88888888-8888-8888-8888-888888888888"
    for sid in (keep_sid, drop1, drop2):
        await storage.save_session_metadata(
            engine, sid, provider="anthropic", model="claude-haiku-4-5",
        )
    # drop1 有 1 個 fork 子孫
    from orion_model.types import NormalizedMessage
    await storage.append_messages(engine, drop1, [
        NormalizedMessage(role="user", content="Q1"),
        NormalizedMessage(role="assistant", content="A1"),
    ])
    drop1_fork = await storage.fork_session(
        engine, source_session_id=drop1, up_to_message_index=1, title="fork",
    )

    stats = await storage.delete_many_sessions(engine, [drop1, drop2])
    assert stats["requested"] == 2
    assert stats["deleted"] == 2
    assert stats["descendants_deleted"] == 1 # drop1_fork

    listed = await storage.list_sessions(engine)
    ids = {s.session_id for s in listed}
    assert keep_sid in ids
    assert drop1 not in ids
    assert drop2 not in ids
    assert drop1_fork not in ids, "fork 子孫該被 cascade"
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_session_cascades_fork_descendants(data_dir: str) -> None:
    """刪 parent session 時,fork 出去的所有子孫(含孫子)一併刪掉。
    原本只刪 parent 會留孤兒,sidebar tree 看起來變 root,user 直覺不對。"""
    os.environ["ORION_COWORK_DATA_DIR"] = data_dir
    from orion_model.types import NormalizedMessage
    from orion_cowork_sidecar import storage

    engine = await storage.init_storage()
    root_sid = "44444444-4444-4444-4444-444444444444"
    await storage.save_session_metadata(
        engine, root_sid, provider="anthropic", model="claude-haiku-4-5",
    )
    await storage.append_messages(engine, root_sid, [
        NormalizedMessage(role="user", content="Q1"),
        NormalizedMessage(role="assistant", content="A1"),
    ])
    # Fork 一次出 child,再從 child fork 一次出 grandchild
    child_sid = await storage.fork_session(
        engine, source_session_id=root_sid, up_to_message_index=1, title="child",
    )
    grand_sid = await storage.fork_session(
        engine, source_session_id=child_sid, up_to_message_index=1, title="grand",
    )
    # 不相關的 session 同時存在,確認 cascade 不會誤刪
    other_sid = "55555555-5555-5555-5555-555555555555"
    await storage.save_session_metadata(
        engine, other_sid, provider="anthropic", model="claude-haiku-4-5",
    )

    assert await storage.count_fork_descendants(engine, root_sid) == 2
    assert await storage.delete_session(engine, root_sid) is True

    listed = await storage.list_sessions(engine)
    ids = {s.session_id for s in listed}
    assert root_sid not in ids
    assert child_sid not in ids, "child fork 應一併刪掉"
    assert grand_sid not in ids, "grandchild fork 應一併刪掉"
    assert other_sid in ids, "無關 session 不該被牽連"
    await engine.dispose()


def test_conversation_delete_persists(data_dir: str) -> None:
    # Create 2 sessions in process A
    frames_a = _run_sidecar([
        '{"id":"1","method":"conversation.create","params":{}}',
        '{"id":"2","method":"conversation.create","params":{}}',
    ], data_dir)
    sid1 = next(f for f in frames_a if f.get("id") == "1")["data"]["session_id"]
    sid2 = next(f for f in frames_a if f.get("id") == "2")["data"]["session_id"]

    # Process B:delete sid1
    _run_sidecar([
        f'{{"id":"d","method":"conversation.delete","params":{{"session_id":"{sid1}"}}}}',
    ], data_dir)

    # Process C:list — should only have sid2
    frames_c = _run_sidecar([
        '{"id":"l","method":"conversation.list"}',
    ], data_dir)
    listed = next(f for f in frames_c if f.get("id") == "l")
    sessions = listed["data"]["sessions"]
    ids = {s["session_id"] for s in sessions}
    assert sid2 in ids
    assert sid1 not in ids


def test_db_file_created_in_data_dir(data_dir: str) -> None:
    _run_sidecar(['{"id":"1","method":"ping"}'], data_dir)
    # Ping doesn't touch DB,但其他 method 會;觸發 list 強制 init
    _run_sidecar(['{"id":"2","method":"conversation.list"}'], data_dir)
    assert Path(data_dir, "sessions", "cowork.db").exists()
