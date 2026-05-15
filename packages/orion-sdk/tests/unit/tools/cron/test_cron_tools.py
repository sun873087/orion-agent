"""Cron tools — create / list / delete + cron expr 驗證。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent
from orion_sdk.tools.cron.cron_create import CronCreateInput, CronCreateTool
from orion_sdk.tools.cron.cron_delete import CronDeleteInput, CronDeleteTool
from orion_sdk.tools.cron.cron_list import CronListInput, CronListTool
from orion_sdk.tools.cron.scheduler import reset_scheduler


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_scheduler()
    yield
    reset_scheduler()


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


def _extract_id(text: str) -> str:
    import json
    return json.loads(text)["id"]


@pytest.mark.asyncio
async def test_create_list_delete() -> None:
    # create
    create = CronCreateTool()
    events = await _collect(
        create.call(
            CronCreateInput(name="job1", cron_expr="0 9 * * 1-5", command="echo hi"),
            AgentContext(),
        ),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    cid = _extract_id(text)

    # list
    events = await _collect(CronListTool().call(CronListInput(), AgentContext()))
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert cid in text and "job1" in text

    # delete
    events = await _collect(
        CronDeleteTool().call(CronDeleteInput(job_id=cid), AgentContext()),
    )
    assert any(isinstance(e, TextEvent) for e in events)

    # list 應為空
    events = await _collect(CronListTool().call(CronListInput(), AgentContext()))
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "no cron jobs" in text


@pytest.mark.asyncio
async def test_invalid_cron_expr() -> None:
    create = CronCreateTool()
    events = await _collect(
        create.call(
            CronCreateInput(name="bad", cron_expr="not valid", command="x"),
            AgentContext(),
        ),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_delete_unknown_id() -> None:
    events = await _collect(
        CronDeleteTool().call(CronDeleteInput(job_id="no-such"), AgentContext()),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)
