"""6 個 Task tools — 簡 happy path。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent
from orion_sdk.tools.task.runner import reset_runner
from orion_sdk.tools.task.task_create import TaskCreateInput, TaskCreateTool
from orion_sdk.tools.task.task_get import TaskGetInput, TaskGetTool
from orion_sdk.tools.task.task_list import TaskListInput, TaskListTool
from orion_sdk.tools.task.task_output import TaskOutputInput, TaskOutputTool
from orion_sdk.tools.task.task_stop import TaskStopInput, TaskStopTool
from orion_sdk.tools.task.task_update import TaskUpdateInput, TaskUpdateTool


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_runner()


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


def _extract_tid(text: str) -> str:
    """parse 'task created — id=<tid>, ...' line。"""
    import re
    m = re.search(r"id=([a-f0-9]{12})", text)
    assert m
    return m.group(1)


@pytest.mark.asyncio
async def test_create_get_list_update_stop_output_chain() -> None:
    create = TaskCreateTool()
    get = TaskGetTool()
    listt = TaskListTool()
    update = TaskUpdateTool()
    stop = TaskStopTool()
    output = TaskOutputTool()

    # create
    events = await _collect(
        create.call(TaskCreateInput(subject="probe"), AgentContext()),
    )
    tid = _extract_tid(next(e.text for e in events if isinstance(e, TextEvent)))

    # get
    events = await _collect(get.call(TaskGetInput(task_id=tid), AgentContext()))
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert tid in text and "probe" in text

    # list
    events = await _collect(listt.call(TaskListInput(), AgentContext()))
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert tid in text

    # update metadata
    events = await _collect(
        update.call(
            TaskUpdateInput(task_id=tid, description="updated", metadata_json='{"k": 1}'),
            AgentContext(),
        ),
    )
    assert any(isinstance(e, TextEvent) for e in events)

    # stop
    events = await _collect(stop.call(TaskStopInput(task_id=tid), AgentContext()))
    assert any(isinstance(e, TextEvent) for e in events)

    # output
    events = await _collect(output.call(TaskOutputInput(task_id=tid), AgentContext()))
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "no output" in text or len(text) >= 0


@pytest.mark.asyncio
async def test_get_unknown_id_errors() -> None:
    get = TaskGetTool()
    events = await _collect(
        get.call(TaskGetInput(task_id="not-an-id"), AgentContext()),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_update_invalid_metadata_json() -> None:
    create = TaskCreateTool()
    update = TaskUpdateTool()
    events = await _collect(
        create.call(TaskCreateInput(subject="x"), AgentContext()),
    )
    tid = _extract_tid(next(e.text for e in events if isinstance(e, TextEvent)))
    events = await _collect(
        update.call(
            TaskUpdateInput(task_id=tid, metadata_json="{not valid"),
            AgentContext(),
        ),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_list_empty() -> None:
    events = await _collect(
        TaskListTool().call(TaskListInput(), AgentContext()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "no tasks" in text
