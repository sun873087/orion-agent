"""TodoWriteTool — 寫 ctx.todos in-memory。"""

from __future__ import annotations

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.todo.todo_write import TodoItem, TodoWriteInput, TodoWriteTool


@pytest.mark.asyncio
async def test_write_todos() -> None:
    ctx = AgentContext()
    tool = TodoWriteTool()
    todos = [
        TodoItem(content="step 1", status="completed"),
        TodoItem(content="step 2", status="in_progress"),
        TodoItem(content="step 3", status="pending"),
    ]
    events = [
        e
        async for e in tool.call(TodoWriteInput(todos=todos), ctx)
    ]
    assert isinstance(events[0], TextEvent)
    assert len(ctx.todos) == 3
    assert ctx.todos[1]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_multiple_in_progress_rejected() -> None:
    ctx = AgentContext()
    tool = TodoWriteTool()
    todos = [
        TodoItem(content="a", status="in_progress"),
        TodoItem(content="b", status="in_progress"),
    ]
    events = [
        e
        async for e in tool.call(TodoWriteInput(todos=todos), ctx)
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "in_progress" in events[0].message


@pytest.mark.asyncio
async def test_clear_list() -> None:
    ctx = AgentContext(todos=[{"content": "old", "status": "pending"}])
    tool = TodoWriteTool()
    events = [
        e
        async for e in tool.call(TodoWriteInput(todos=[]), ctx)
    ]
    assert isinstance(events[0], TextEvent)
    assert ctx.todos == []


@pytest.mark.asyncio
async def test_replaces_not_appends() -> None:
    """既有 todos 應被覆寫(不是 append)。"""
    ctx = AgentContext(
        todos=[{"content": "old", "status": "completed"}]
    )
    tool = TodoWriteTool()
    new_list = [TodoItem(content="brand new", status="pending")]
    _ = [e async for e in tool.call(TodoWriteInput(todos=new_list), ctx)]
    assert len(ctx.todos) == 1
    assert ctx.todos[0]["content"] == "brand new"
