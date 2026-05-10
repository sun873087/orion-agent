"""compute_message_breakpoints — Stage 3 rolling cache 邏輯。"""

from __future__ import annotations

from orion_agent.core.message_cache import compute_message_breakpoints
from orion_agent.llm.types import NormalizedMessage


def _u(text: str) -> NormalizedMessage:
    return NormalizedMessage(role="user", content=text)


def _a(text: str) -> NormalizedMessage:
    return NormalizedMessage(role="assistant", content=text)


def test_empty_messages_returns_empty() -> None:
    assert compute_message_breakpoints([]) == []


def test_single_user_message_one_bp() -> None:
    """第一 turn 只寫一次 cache。"""
    bps = compute_message_breakpoints([_u("hi")])
    assert bps == [0]


def test_state_ending_with_assistant_uncommon_but_handled() -> None:
    """[u1, a1] 不該在 stream 時送(state 永遠以 user 結尾),但函式不該 crash。

    回 [0, 1] — 兩個 bp 都標,雖然這 case 不該發生。
    """
    bps = compute_message_breakpoints([_u("hi"), _a("hello")])
    assert bps == [0, 1]


def test_second_user_turn_two_bps() -> None:
    """[u1, a1, u2] → [0, 2]:u1 hit 上 turn 寫,u2 寫新。"""
    msgs = [_u("hi"), _a("hello"), _u("more")]
    assert compute_message_breakpoints(msgs) == [0, 2]


def test_third_turn_rolls_forward() -> None:
    """[u1, a1, u2, a2, u3] → [2, 4]:bp 滾到較新位置。"""
    msgs = [_u("hi"), _a("hello"), _u("more"), _a("ok"), _u("again")]
    assert compute_message_breakpoints(msgs) == [2, 4]


def test_long_conversation_only_two_bps() -> None:
    """5 turn:仍只回 2 個 bp(最新 user + 上一個 user)。"""
    msgs: list[NormalizedMessage] = []
    for i in range(5):
        msgs.append(_u(f"u{i}"))
        msgs.append(_a(f"a{i}"))
    msgs.append(_u("latest"))
    bps = compute_message_breakpoints(msgs)
    assert len(bps) == 2
    # 最後 message
    assert bps[-1] == len(msgs) - 1
    # 倒數第二個 user message(在 latest 之前的 user)
    assert msgs[bps[0]].role == "user"
    assert msgs[bps[0]].content == "u4"


def test_no_prior_user_when_only_assistants_before() -> None:
    """邊界(理論上不該發生):若前面只有 asst,只回最後 bp。"""
    msgs = [_a("a"), _a("b"), _u("u")]
    assert compute_message_breakpoints(msgs) == [2]


def test_bps_returned_sorted() -> None:
    """回傳 list 應 sorted,讓下游處理一致。"""
    msgs = [_u("u1"), _a("a1"), _u("u2")]
    bps = compute_message_breakpoints(msgs)
    assert bps == sorted(bps)
