"""GrepTool — content search。

優先 shell out 到 ripgrep(`rg`)— 快、會 honour .gitignore。
找不到 rg → fallback 純 Python re 遍歷。

對應 TS Claude Code `src/tools/GrepTool/`。
"""

from __future__ import annotations

import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import anyio
from pydantic import Field

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent, ToolInput

_MAX_MATCHES = 500
_MAX_OUTPUT_BYTES = 50_000


class GrepInput(ToolInput):
    """GrepTool 的 input schema。"""

    pattern: str = Field(..., description="Regex pattern (Python / ripgrep syntax).")
    path: str | None = Field(
        default=None,
        description="Absolute directory or file to search. Defaults to current process cwd.",
    )
    file_pattern: str | None = Field(
        default=None,
        description="Optional glob to limit which files (e.g. '*.py'). ripgrep -g flag.",
    )
    case_sensitive: bool = Field(default=True, description="Case-sensitive match.")


class GrepTool:
    name = "Grep"
    description = (
        "Search file contents by regex. Uses ripgrep if installed, else a Python "
        "fallback. Returns matching lines with file path and line number."
    )
    input_schema = GrepInput

    async def call(
        self,
        input: GrepInput,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        search_path_str = input.path or str(ctx.cwd)
        search_path = Path(search_path_str)

        if not search_path.is_absolute():
            yield ErrorEvent(message=f"path must be absolute: {search_path_str!r}")
            return

        if not search_path.exists():
            yield ErrorEvent(message=f"path does not exist: {search_path}")
            return

        rg = shutil.which("rg")
        if rg:
            async for ev in self._run_ripgrep(rg, input, search_path):
                yield ev
        else:
            async for ev in self._run_python_fallback(input, search_path):
                yield ev

    async def _run_ripgrep(
        self,
        rg_path: str,
        input: GrepInput,
        search_path: Path,
    ) -> AsyncIterator[ToolEvent]:
        argv = [
            rg_path,
            "--line-number",
            "--no-heading",
            "--color", "never",
            "--max-count", "20",  # 每檔最多 20 match
        ]
        if not input.case_sensitive:
            argv.append("--ignore-case")
        if input.file_pattern:
            argv.extend(["--glob", input.file_pattern])
        argv.extend(["--", input.pattern, str(search_path)])

        try:
            result = await anyio.run_process(
                argv,
                check=False,
                stdout=-1,
                stderr=-1,
            )
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(message=f"ripgrep failed to run: {type(e).__name__}: {e}")
            return

        out = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        err = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

        # rg exit 1 = no match(不算錯)
        if result.returncode not in (0, 1):
            yield ErrorEvent(
                message=f"ripgrep exit {result.returncode}: {err.strip() or '(no stderr)'}"
            )
            return

        if not out.strip():
            yield TextEvent(text=f"(no matches for {input.pattern!r} in {search_path})")
            return

        if len(out) > _MAX_OUTPUT_BYTES:
            out = out[:_MAX_OUTPUT_BYTES] + f"\n... (truncated at {_MAX_OUTPUT_BYTES} bytes)"
        yield TextEvent(text=out)

    async def _run_python_fallback(
        self,
        input: GrepInput,
        search_path: Path,
    ) -> AsyncIterator[ToolEvent]:
        try:
            flags = 0 if input.case_sensitive else re.IGNORECASE
            regex = re.compile(input.pattern, flags=flags)
        except re.error as e:
            yield ErrorEvent(message=f"invalid regex: {e}")
            return

        if search_path.is_file():
            files = [search_path]
        else:
            pattern = input.file_pattern or "**/*"
            files = [p for p in search_path.glob(pattern) if p.is_file()]

        results: list[str] = []
        match_count = 0
        bytes_count = 0
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    chunk = f"{path}:{i}:{line}\n"
                    if bytes_count + len(chunk) > _MAX_OUTPUT_BYTES:
                        results.append(f"... (truncated at {_MAX_OUTPUT_BYTES} bytes)\n")
                        break
                    results.append(chunk)
                    bytes_count += len(chunk)
                    match_count += 1
                    if match_count >= _MAX_MATCHES:
                        results.append(f"... (truncated at {_MAX_MATCHES} matches)\n")
                        break
            if match_count >= _MAX_MATCHES or bytes_count >= _MAX_OUTPUT_BYTES:
                break

        if not results:
            yield TextEvent(text=f"(no matches for {input.pattern!r} in {search_path})")
            return

        yield TextEvent(text="".join(results))

    def is_concurrency_safe(self, input: GrepInput) -> bool:  # noqa: ARG002
        return True  # 純讀

    def is_read_only(self, input: GrepInput) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return _MAX_OUTPUT_BYTES
