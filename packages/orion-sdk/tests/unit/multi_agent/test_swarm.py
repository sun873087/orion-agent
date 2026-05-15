"""SwarmRunner — Phase 15。"""

from __future__ import annotations

import pytest

from orion_sdk.multi_agent.swarm import (
    SwarmAgent,
    SwarmConfig,
    SwarmRunner,
)
from tests.conftest import MockProvider, MockTurn


def _agents(*names_with_role: tuple[str, str, str]) -> list[SwarmAgent]:
    return [
        SwarmAgent(
            name=n,
            role=r,
            system_prompt=f"You are {n} ({r}).",
            initial_prompt=initial,
        )
        for n, r, initial in names_with_role
    ]


@pytest.mark.asyncio
async def test_two_agent_mention_routes() -> None:
    """A 在 initial 寫 @b: hi → B 收到並回 → A 收到 B 的回應。"""
    # MockProvider turns:用一份 list 共用,模擬「下一輪輸出什麼」按 stream 順序
    provider = MockProvider(turns=[
        # Round 1 (a 的 initial turn)
        MockTurn(text="@b: hello b, please reply."),
        # Round 2 (b 收到,回應)
        MockTurn(text="@a: hi a, got your message."),
        # Round 3 (a 收到 b 的回應,回應一次)
        MockTurn(text="thanks b"),
    ])

    config = SwarmConfig(
        agents=_agents(
            ("a", "asker", "say hi to b"),
            ("b", "responder", ""),  # empty initial → b 等 mention 才動作
        ),
        max_rounds=3,
    )
    runner = SwarmRunner(config=config, provider=provider)  # type: ignore[arg-type]
    result = await runner.run()

    # 雙方都至少跑過一輪
    assert result.rounds_run["a"] >= 1
    assert result.rounds_run["b"] >= 1

    # a 有送 1+ 訊息給 b
    a_log = result.logs["a"]
    sent_targets = {m.to_agent for m in a_log.sent_messages}
    assert "b" in sent_targets


@pytest.mark.asyncio
async def test_max_rounds_caps() -> None:
    """設 max_rounds=2,單 agent 不會跑超過 2 輪。"""
    provider = MockProvider(turns=[
        MockTurn(text="@b: ping"),
        MockTurn(text="@a: pong"),
        MockTurn(text="@b: ping2"),
        MockTurn(text="@a: pong2"),
        MockTurn(text="@b: ping3"),
        MockTurn(text="@a: pong3"),
        MockTurn(text="@b: ping4"),
        MockTurn(text="@a: pong4"),
    ])
    config = SwarmConfig(
        agents=_agents(
            ("a", "asker", "start"),
            ("b", "responder", ""),
        ),
        max_rounds=2,
    )
    runner = SwarmRunner(config=config, provider=provider)  # type: ignore[arg-type]
    result = await runner.run()

    for name in ("a", "b"):
        assert result.rounds_run[name] <= 2


@pytest.mark.asyncio
async def test_leader_stop_swarm() -> None:
    """leader 在回應寫 STOP_SWARM → 立即結束整個 swarm。"""
    provider = MockProvider(turns=[
        # leader 一開口就 STOP
        MockTurn(text="STOP_SWARM — done quickly."),
        MockTurn(text="@l: i was not even mentioned"),
    ])
    config = SwarmConfig(
        agents=_agents(
            ("l", "leader", "lead the discussion"),
            ("w", "worker", ""),
        ),
        leader="l",
        max_rounds=10,
    )
    runner = SwarmRunner(config=config, provider=provider)  # type: ignore[arg-type]
    result = await runner.run()

    assert result.stopped_by_leader is True
    # leader 跑了 1 輪,worker 0 輪(因為 leader 沒 mention 它,bus 早已 close)
    assert result.rounds_run["l"] == 1
    assert result.rounds_run["w"] == 0


@pytest.mark.asyncio
async def test_dup_agent_names_raises() -> None:
    config = SwarmConfig(
        agents=_agents(
            ("a", "x", "i"),
            ("a", "y", "i"),
        ),
    )
    with pytest.raises(ValueError, match="duplicate"):
        SwarmRunner(config=config, provider=MockProvider())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unknown_leader_raises() -> None:
    config = SwarmConfig(
        agents=_agents(("a", "x", "i")),
        leader="ghost",
    )
    with pytest.raises(ValueError, match="leader"):
        SwarmRunner(config=config, provider=MockProvider())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_empty_initial_prompt_skips_first_turn() -> None:
    """initial_prompt='' 的 agent 不會在 round 1 就跑。"""
    provider = MockProvider(turns=[
        MockTurn(text="@b: hi"),  # a 的 initial
        MockTurn(text="@a: ok"),  # b 收到後
    ])
    config = SwarmConfig(
        agents=_agents(
            ("a", "x", "say hi"),
            ("b", "y", ""),  # empty
        ),
        max_rounds=2,
    )
    runner = SwarmRunner(config=config, provider=provider)  # type: ignore[arg-type]
    result = await runner.run()
    # b 等 a 的 mention,b 第一條訊息 history 應該是 user(來自 a)
    b_msgs = result.logs["b"].messages
    assert len(b_msgs) >= 1
    assert b_msgs[0].role == "user"


@pytest.mark.asyncio
async def test_self_mention_ignored() -> None:
    """agent 寫 @<自己>: ... → bus 不投遞(防自言自語成迴圈)。"""
    provider = MockProvider(turns=[
        MockTurn(text="@a: pretending to talk to myself"),
    ])
    config = SwarmConfig(
        agents=_agents(("a", "x", "test")),
        max_rounds=3,
    )
    runner = SwarmRunner(config=config, provider=provider)  # type: ignore[arg-type]
    result = await runner.run()

    a_sent = result.logs["a"].sent_messages
    assert all(m.to_agent != "a" for m in a_sent)
