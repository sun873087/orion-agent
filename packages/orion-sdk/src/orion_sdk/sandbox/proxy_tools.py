"""Sandbox-aware proxy tools — Phase 7。

對應 spec § 5 proxy_tools.py。

Phase 1 既有 BashTool / FileWriteTool / FileEditTool / FileReadTool **直接動 host**。
proxy_tools 提供「同 input schema、改透過 SandboxBackend 執行」的版本:
- SandboxedBashTool
- SandboxedFileWriteTool
- SandboxedFileEditTool
- SandboxedFileReadTool

Conversation 啟用 sandbox 時 swap 到此版本。Tool name / description / input_schema
不變(模型看到的工具一樣),只是執行路徑改走 backend。

is_concurrency_safe:讀類 True(LocalBackend / DockerBackend 都單一 container,
讀並發安全)。寫類 False。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent, ToolEvent
from orion_sdk.sandbox.protocol import SandboxBackend, SandboxError
from orion_sdk.tools.file.edit import FileEditInput
from orion_sdk.tools.file.read import FileReadInput
from orion_sdk.tools.file.write import FileWriteInput
from orion_sdk.tools.shell.bash import BashInput


class SandboxedBashTool:
    name = "Bash"
    description = (
        "Run a shell command inside the sandbox. Same as the host Bash tool, "
        "but isolated per-conversation."
    )
    input_schema = BashInput

    def __init__(self, backend: SandboxBackend) -> None:
        self._backend = backend

    async def call(
        self,
        input: BashInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        try:
            result = await self._backend.exec(
                ["/bin/bash", "-c", input.command],
                cwd=input.cwd,
                timeout=float(input.timeout_seconds),
            )
        except SandboxError as e:
            yield ErrorEvent(message=str(e))
            return

        header = f"$ {input.command}\n[exit {result.exit_code}]\n"
        body = result.stdout if result.stdout else "(no output)"
        if result.truncated:
            body += "\n... [output truncated]"
        full = header + body
        if result.exit_code != 0:
            yield ErrorEvent(message=full)
        else:
            yield TextEvent(text=full)

    def is_concurrency_safe(self, input: BashInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: BashInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 30_000


class SandboxedFileReadTool:
    name = "Read"
    description = (
        "Read a text file from the sandbox by absolute path. "
        "Returns content with line numbers."
    )
    input_schema = FileReadInput

    def __init__(self, backend: SandboxBackend) -> None:
        self._backend = backend

    async def call(
        self,
        input: FileReadInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = await self._backend.read_file(input.path)
        except SandboxError as e:
            yield ErrorEvent(message=str(e))
            return

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            yield ErrorEvent(message=f"file is not valid UTF-8: {input.path}")
            return

        lines = text.splitlines()
        end = min(input.offset + input.limit, len(lines))
        selected = lines[input.offset:end]
        numbered = "\n".join(
            f"{i + 1 + input.offset}\t{line}" for i, line in enumerate(selected)
        )
        yield TextEvent(text=numbered or "(empty file)")

    def is_concurrency_safe(self, input: FileReadInput) -> bool:  # noqa: ARG002
        return True

    def is_read_only(self, input: FileReadInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 100_000


class SandboxedFileWriteTool:
    name = "Write"
    description = (
        "Write content to a file in the sandbox at an absolute path. "
        "Overwrites if the file exists."
    )
    input_schema = FileWriteInput

    def __init__(self, backend: SandboxBackend) -> None:
        self._backend = backend

    async def call(
        self,
        input: FileWriteInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        try:
            await self._backend.write_file(input.path, input.content.encode("utf-8"))
        except SandboxError as e:
            yield ErrorEvent(message=str(e))
            return
        yield TextEvent(
            text=f"wrote {input.path} ({len(input.content)} chars, "
            f"{len(input.content.splitlines())} lines)"
        )

    def is_concurrency_safe(self, input: FileWriteInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: FileWriteInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000


class SandboxedFileEditTool:
    name = "Edit"
    description = (
        "Replace text in a file in the sandbox. old_string must match exactly; "
        "set replace_all=True for multiple occurrences."
    )
    input_schema = FileEditInput

    def __init__(self, backend: SandboxBackend) -> None:
        self._backend = backend

    async def call(
        self,
        input: FileEditInput,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        try:
            data = await self._backend.read_file(input.path)
            text = data.decode("utf-8")
        except SandboxError as e:
            yield ErrorEvent(message=str(e))
            return
        except UnicodeDecodeError:
            yield ErrorEvent(message=f"not valid UTF-8: {input.path}")
            return

        if input.old_string == input.new_string:
            yield ErrorEvent(message="old_string == new_string — no change")
            return
        if input.old_string not in text:
            yield ErrorEvent(message=f"old_string not found in {input.path}")
            return

        count = text.count(input.old_string)
        if not input.replace_all and count > 1:
            yield ErrorEvent(
                message=(
                    f"old_string appears {count} times — provide more context "
                    "or set replace_all=True"
                )
            )
            return

        new_text = (
            text.replace(input.old_string, input.new_string)
            if input.replace_all
            else text.replace(input.old_string, input.new_string, 1)
        )

        try:
            await self._backend.write_file(input.path, new_text.encode("utf-8"))
        except SandboxError as e:
            yield ErrorEvent(message=str(e))
            return

        replaced = count if input.replace_all else 1
        yield TextEvent(
            text=f"edited {input.path} — {replaced} occurrence(s) replaced"
        )

    def is_concurrency_safe(self, input: FileEditInput) -> bool:  # noqa: ARG002
        return False

    def is_read_only(self, input: FileEditInput) -> bool:  # noqa: ARG002
        return False

    def max_result_size_chars(self) -> int | float:
        return 1_000


def build_sandboxed_tools(backend: SandboxBackend) -> list[object]:
    """工廠 — 取代 main.py 的 _build_tools 中 Bash/Read/Write/Edit 部分。

    回的物件已符合 Tool Protocol。
    """
    return [
        SandboxedBashTool(backend),
        SandboxedFileReadTool(backend),
        SandboxedFileWriteTool(backend),
        SandboxedFileEditTool(backend),
    ]
