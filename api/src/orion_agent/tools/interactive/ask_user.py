"""AskUserQuestionTool — Phase 10。對應 TS AskUserQuestionTool。

讓 agent 在對話中反問 user(選擇題或開放式)。caller 注入 `AskUserCallback`,
本 tool 把 question 丟出去等回答。

兩個內建 asker:
- `make_stdin_asker()`:CLI 模式,直接 print + input()(blocking,跑在 thread)
- `make_ws_asker(outbound_queue, pending)`:WebSocket 模式,丟事件等 reader resolve

範例:
```python
asker = make_stdin_asker()
tool = AskUserQuestionTool(asker=asker)
```
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import anyio
from pydantic import BaseModel, Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_ASK_TIMEOUT_S = 300.0  # 5 min


# ─── Question 結構 ──────────────────────────────────────────────────────


class AskOption(BaseModel):
    """單一選項。"""

    label: str = Field(..., description="The display text shown to the user.")
    description: str = Field(default="", description="Tooltip explaining this option.")


class AskQuestion(BaseModel):
    """One question with options."""

    question: str = Field(..., description="The question text.")
    header: str = Field(default="", description="Short label / chip (≤ 12 chars).")
    options: list[AskOption] = Field(
        default_factory=list,
        description=(
            "List of options the user can choose from. Empty = open-ended text answer."
        ),
    )
    multi_select: bool = Field(
        default=False,
        description="If True, user can pick multiple options.",
    )


class AskUserQuestionInput(ToolInput):
    """模型呼叫格式:可一次問多題(同 Claude AskUserQuestion convention)。"""

    questions: list[AskQuestion] = Field(
        ...,
        description="One or more questions to ask the user.",
        min_length=1,
        max_length=4,
    )


# ─── Callback contract ──────────────────────────────────────────────────


AskUserCallback = Callable[[list[dict[str, Any]]], Awaitable[dict[str, str]]]
"""(serialized_questions: list[dict]) → answers: dict[question_text -> selected_label]."""


# ─── WebSocket-flavored async pending(同 permission round-trip)─────────


@dataclass
class PendingQuestions:
    """state shared between asker callback + ws reader task。"""

    pending: dict[str, asyncio.Future[dict[str, str]]] = field(default_factory=dict)

    def resolve(self, request_id: str, answers: dict[str, str]) -> None:
        fut = self.pending.pop(request_id, None)
        if fut is None or fut.done():
            return
        fut.set_result(answers)


def make_ws_asker(
    *,
    outbound_queue: Any,
    pending: PendingQuestions,
    timeout_s: float = _ASK_TIMEOUT_S,
) -> AskUserCallback:
    """WebSocket 版 — 丟事件 → 等 ws reader resolve。

    `outbound_queue` 期望 anyio MemoryObjectSendStream(`.send(...)` async)
    或 asyncio.Queue(`.put(...)`)。dynamic dispatch 兩種都吃。
    """
    async def asker(questions: list[dict[str, Any]]) -> dict[str, str]:
        request_id = uuid4().hex[:16]
        future: asyncio.Future[dict[str, str]] = asyncio.get_running_loop().create_future()
        pending.pending[request_id] = future

        event = {
            "type": "ask_user_question",
            "request_id": request_id,
            "questions": questions,
        }
        # anyio MemoryObjectSendStream 用 .send(),asyncio.Queue 用 .put()
        if hasattr(outbound_queue, "send"):
            await outbound_queue.send(event)
        else:
            await outbound_queue.put(event)

        try:
            return await asyncio.wait_for(future, timeout=timeout_s)
        except TimeoutError:
            pending.pending.pop(request_id, None)
            return {}

    return asker


# ─── CLI stdin asker(blocking input wrapped in thread)──────────────────


def make_stdin_asker() -> AskUserCallback:
    """CLI 版:print 題目 → 等 stdin。"""

    async def asker(questions: list[dict[str, Any]]) -> dict[str, str]:
        def _ask_blocking() -> dict[str, str]:
            answers: dict[str, str] = {}
            for q in questions:
                qtext = str(q.get("question", "?"))
                options = q.get("options") or []
                print("\n[ASK USER]", qtext, file=sys.stderr, flush=True)
                if options:
                    for i, opt in enumerate(options, 1):
                        label = opt.get("label", "?") if isinstance(opt, dict) else str(opt)
                        print(f"  {i}. {label}", file=sys.stderr, flush=True)
                    print("(enter number or label)", file=sys.stderr, flush=True)
                else:
                    print("(open-ended — type your answer)", file=sys.stderr, flush=True)
                try:
                    raw = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    return answers

                if options and raw.isdigit():
                    idx = int(raw) - 1
                    if 0 <= idx < len(options):
                        opt = options[idx]
                        chosen = opt.get("label", str(opt)) if isinstance(opt, dict) else str(opt)
                        answers[qtext] = chosen
                        continue
                answers[qtext] = raw
            return answers

        return await anyio.to_thread.run_sync(_ask_blocking)

    return asker


# ─── Tool ────────────────────────────────────────────────────────────────


class AskUserQuestionTool:
    name = "AskUserQuestion"
    description = (
        "Ask the user one or more questions and wait for their answer. "
        "Use when you genuinely need user input to proceed; do not over-use."
    )
    input_schema = AskUserQuestionInput
    should_defer = True
    """這支 tool 通常 deferred(預設不放 system prompt,要時用 ToolSearch 載)。"""

    def __init__(self, asker: AskUserCallback | None = None) -> None:
        self.asker = asker

    async def call(
        self,
        input: AskUserQuestionInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        if self.asker is None:
            yield ErrorEvent(
                message=(
                    "AskUserQuestion is not wired up — no interactive channel "
                    "(WebSocket or stdin)."
                ),
            )
            return

        serialized = [q.model_dump() for q in input.questions]
        try:
            answers = await self.asker(serialized)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"asker failed: {type(e).__name__}: {e}")
            return

        if not answers:
            yield TextEvent(
                text="(user did not respond / timed out)",
            )
            return

        lines = ["User answers:"]
        for q, a in answers.items():
            lines.append(f"  - {q!r}: {a!r}")
        yield TextEvent(text="\n".join(lines))

    def is_concurrency_safe(self, input: AskUserQuestionInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: AskUserQuestionInput) -> bool:  # noqa: ARG002
        return True  # 不改 fs / state

    def max_result_size_chars(self) -> int | float:
        return 5_000
