"""NotebookEditTool — Phase 10。對應 TS NotebookEditTool。

Jupyter `.ipynb` 檔案 cell 操作:insert / replace / delete。

用 `nbformat` 解析 / 序列化(保留 metadata、outputs、execution_count 等)。

Action:
- replace:取代 cell `index` 的 source(content);保留 cell_type
- insert:在 `index` 前插入新 cell(cell_type 由 input 決定,預設 code)
- delete:刪 `index` 的 cell

Anthropic 文件提到要小心 outputs:replace cell 時清掉舊 outputs(因為新 source 應重跑)。
delete 整 cell 也清掉。

預設不執行 cell — 純檔操作。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

import anyio
import nbformat
from pydantic import Field

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_MAX_CELL_LEN = 100_000


class NotebookEditInput(ToolInput):
    path: str = Field(..., description="Absolute path to the .ipynb file.")
    action: Literal["replace", "insert", "delete"] = Field(
        ..., description="What to do.",
    )
    index: int = Field(
        ..., ge=0, description="Cell index (0-based). For insert, new cell goes here.",
    )
    content: str = Field(
        default="",
        description="New cell source (required for replace/insert).",
    )
    cell_type: Literal["code", "markdown", "raw"] = Field(
        default="code",
        description="Cell type for insert action; ignored for replace/delete.",
    )


class NotebookEditTool:
    name = "NotebookEdit"
    description = (
        "Edit a Jupyter notebook (.ipynb): replace, insert, or delete a cell by index."
    )
    input_schema = NotebookEditInput

    async def call(
        self,
        input: NotebookEditInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        path = Path(input.path)
        if not path.is_absolute():
            yield ErrorEvent(message=f"path must be absolute: {input.path!r}")
            return
        if not path.exists():
            yield ErrorEvent(message=f"notebook does not exist: {path}")
            return
        if path.suffix != ".ipynb":
            yield ErrorEvent(message=f"not a .ipynb file: {path}")
            return
        if len(input.content) > _MAX_CELL_LEN:
            yield ErrorEvent(
                message=f"content too large: {len(input.content)} > {_MAX_CELL_LEN}",
            )
            return

        try:
            nb = await anyio.to_thread.run_sync(_read_notebook, path)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"failed to parse notebook: {e}")
            return

        n_cells = len(nb.cells)

        if input.action == "delete":
            if input.index >= n_cells:
                yield ErrorEvent(
                    message=f"index {input.index} out of range (notebook has {n_cells} cells)",
                )
                return
            del nb.cells[input.index]
            verb = "deleted"

        elif input.action == "replace":
            if input.index >= n_cells:
                yield ErrorEvent(
                    message=f"index {input.index} out of range (notebook has {n_cells} cells)",
                )
                return
            cell = nb.cells[input.index]
            cell["source"] = input.content
            # 清掉 outputs / execution_count(source 改了 → 舊 outputs 不對)
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
            verb = "replaced"

        elif input.action == "insert":
            if input.index > n_cells:
                yield ErrorEvent(
                    message=f"index {input.index} out of range (notebook has {n_cells} cells)",
                )
                return
            new_cell = _make_cell(input.cell_type, input.content)
            nb.cells.insert(input.index, new_cell)
            verb = "inserted"

        else:
            yield ErrorEvent(message=f"unknown action: {input.action!r}")
            return

        try:
            await anyio.to_thread.run_sync(_write_notebook, path, nb)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"failed to write notebook: {e}")
            return

        yield TextEvent(
            text=(
                f"{verb} cell {input.index} in {path} "
                f"(now {len(nb.cells)} cells total)"
            ),
        )

    def is_concurrency_safe(self, input: NotebookEditInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: NotebookEditInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000


# ─── helpers ─────────────────────────────────────────────────────────────


def _read_notebook(path: Path) -> Any:
    return nbformat.read(str(path), as_version=4)  # type: ignore[no-untyped-call]


def _write_notebook(path: Path, nb: Any) -> None:
    nbformat.write(nb, str(path))  # type: ignore[no-untyped-call]


def _make_cell(cell_type: str, source: str) -> Any:
    if cell_type == "markdown":
        return nbformat.v4.new_markdown_cell(source=source)  # type: ignore[no-untyped-call]
    if cell_type == "raw":
        return nbformat.v4.new_raw_cell(source=source)  # type: ignore[no-untyped-call]
    return nbformat.v4.new_code_cell(source=source)  # type: ignore[no-untyped-call]
