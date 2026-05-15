"""NotebookEditTool — replace / insert / delete cell。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import nbformat
import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent
from orion_sdk.tools.file.notebook_edit import (
    NotebookEditInput,
    NotebookEditTool,
)


def _make_notebook(path: Path, sources: list[str]) -> None:
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell(source=s) for s in sources]
    nbformat.write(nb, str(path))


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


@pytest.mark.asyncio
async def test_replace_cell(tmp_path: Path) -> None:
    nb_path = tmp_path / "nb.ipynb"
    _make_notebook(nb_path, ["print(1)", "print(2)"])
    tool = NotebookEditTool()
    events = await _collect(
        tool.call(
            NotebookEditInput(
                path=str(nb_path), action="replace", index=1, content="print(99)",
            ),
            AgentContext(),
        ),
    )
    assert any(isinstance(e, TextEvent) for e in events)
    nb = nbformat.read(str(nb_path), as_version=4)
    assert nb.cells[1]["source"] == "print(99)"


@pytest.mark.asyncio
async def test_insert_cell(tmp_path: Path) -> None:
    nb_path = tmp_path / "nb.ipynb"
    _make_notebook(nb_path, ["a", "b"])
    tool = NotebookEditTool()
    await _collect(
        tool.call(
            NotebookEditInput(
                path=str(nb_path),
                action="insert",
                index=1,
                content="middle",
                cell_type="markdown",
            ),
            AgentContext(),
        ),
    )
    nb = nbformat.read(str(nb_path), as_version=4)
    assert len(nb.cells) == 3
    assert nb.cells[1]["source"] == "middle"
    assert nb.cells[1]["cell_type"] == "markdown"


@pytest.mark.asyncio
async def test_delete_cell(tmp_path: Path) -> None:
    nb_path = tmp_path / "nb.ipynb"
    _make_notebook(nb_path, ["a", "b", "c"])
    tool = NotebookEditTool()
    await _collect(
        tool.call(
            NotebookEditInput(path=str(nb_path), action="delete", index=1),
            AgentContext(),
        ),
    )
    nb = nbformat.read(str(nb_path), as_version=4)
    assert len(nb.cells) == 2
    assert [c["source"] for c in nb.cells] == ["a", "c"]


@pytest.mark.asyncio
async def test_relative_path_rejected(tmp_path: Path) -> None:  # noqa: ARG001
    tool = NotebookEditTool()
    events = await _collect(
        tool.call(
            NotebookEditInput(path="rel/x.ipynb", action="delete", index=0),
            AgentContext(),
        ),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_index_out_of_range(tmp_path: Path) -> None:
    nb_path = tmp_path / "nb.ipynb"
    _make_notebook(nb_path, ["only"])
    tool = NotebookEditTool()
    events = await _collect(
        tool.call(
            NotebookEditInput(path=str(nb_path), action="delete", index=99),
            AgentContext(),
        ),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_replace_clears_outputs(tmp_path: Path) -> None:
    """source 改了 → 舊 outputs 應清掉。"""
    nb_path = tmp_path / "nb.ipynb"
    nb = nbformat.v4.new_notebook()
    cell = nbformat.v4.new_code_cell(source="print(1)")
    cell["outputs"] = [
        nbformat.v4.new_output(output_type="stream", name="stdout", text="1\n"),
    ]
    cell["execution_count"] = 5
    nb.cells = [cell]
    nbformat.write(nb, str(nb_path))

    # 確認寫入時有 outputs
    nb_before = nbformat.read(str(nb_path), as_version=4)
    assert len(nb_before.cells[0]["outputs"]) == 1

    tool = NotebookEditTool()
    await _collect(
        tool.call(
            NotebookEditInput(
                path=str(nb_path), action="replace", index=0, content="print(2)",
            ),
            AgentContext(),
        ),
    )
    nb_after = nbformat.read(str(nb_path), as_version=4)
    assert nb_after.cells[0]["outputs"] == []
    assert nb_after.cells[0]["execution_count"] is None
