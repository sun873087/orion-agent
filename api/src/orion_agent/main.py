"""Phase 1 demo CLI — 完整 agent loop。

跑法:
  orion --provider anthropic --model claude-sonnet-4-6 "Look at /etc and tell me about it"
  orion --provider openai    --model gpt-4o-mini       "..."

支援多 turn 對話、平行工具執行、permission policy(預設 always_allow)、
streaming text + tool 進度顯示。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated, Any

import typer
from dotenv import load_dotenv

# 載入 .env(若存在)— 注入 API keys。必須在 import provider 之前。
load_dotenv()

from orion_agent.core.conversation import Conversation  # noqa: E402
from orion_agent.core.query_loop import (  # noqa: E402
    AssistantTextDelta,
    AssistantThinkingDelta,
    AssistantTurnComplete,
    LoopTerminated,
)
from orion_agent.core.state import AgentContext  # noqa: E402
from orion_agent.core.tool import ErrorEvent, ProgressEvent, TextEvent, Tool  # noqa: E402
from orion_agent.core.tool_execution import (  # noqa: E402
    ToolProgressUpdate,
    ToolResultUpdate,
)
from orion_agent.llm.provider import get_provider  # noqa: E402
from orion_agent.services.feature_flags import load_feature_flags  # noqa: E402
from orion_agent.tools.agent.skill_tool import SkillTool  # noqa: E402
from orion_agent.tools.config.config_tool import ConfigTool  # noqa: E402
from orion_agent.tools.cron.cron_create import CronCreateTool  # noqa: E402
from orion_agent.tools.cron.cron_delete import CronDeleteTool  # noqa: E402
from orion_agent.tools.cron.cron_list import CronListTool  # noqa: E402
from orion_agent.tools.file.edit import FileEditTool  # noqa: E402
from orion_agent.tools.file.notebook_edit import NotebookEditTool  # noqa: E402
from orion_agent.tools.file.read import FileReadTool  # noqa: E402
from orion_agent.tools.file.write import FileWriteTool  # noqa: E402
from orion_agent.tools.interactive.ask_user import (  # noqa: E402
    AskUserQuestionTool,
    make_stdin_asker,
)
from orion_agent.tools.search.glob import GlobTool  # noqa: E402
from orion_agent.tools.search.grep import GrepTool  # noqa: E402
from orion_agent.tools.shell.bash import BashTool  # noqa: E402
from orion_agent.tools.special.sleep import SleepTool  # noqa: E402
from orion_agent.tools.special.synthetic_output import (  # noqa: E402
    SyntheticOutputTool,
)
from orion_agent.tools.special.tool_search import ToolSearchTool  # noqa: E402
from orion_agent.tools.task.task_create import TaskCreateTool  # noqa: E402
from orion_agent.tools.task.task_get import TaskGetTool  # noqa: E402
from orion_agent.tools.task.task_list import TaskListTool  # noqa: E402
from orion_agent.tools.task.task_output import TaskOutputTool  # noqa: E402
from orion_agent.tools.task.task_stop import TaskStopTool  # noqa: E402
from orion_agent.tools.task.task_update import TaskUpdateTool  # noqa: E402
from orion_agent.tools.todo.todo_write import TodoWriteTool  # noqa: E402
from orion_agent.tools.web.fetch import WebFetchTool  # noqa: E402
from orion_agent.tools.workdir.enter import EnterWorkdirTool  # noqa: E402
from orion_agent.tools.workdir.exit import ExitWorkdirTool  # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True)


# Phase 4:system prompt 改由 Conversation 自己組(prompt/static_sections + 動態段)。
# 不再在 main.py 寫死 — Conversation(system_prompt="") 會走 assembler 路徑。


def _build_tools() -> list[Tool[Any]]:
    """註冊所有內建工具。AgentTool 不放這(避免子 agent 自我遞迴)。

    Phase 10 加 ~17 個新工具(special / config / interactive / notebook / task / cron / workdir)。
    """
    base: list[Tool[Any]] = [
        # Phase 1 — 基礎
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
        WebFetchTool(),
        SkillTool(),
        TodoWriteTool(),
        # Phase 9 — workdir(取代 worktree)
        EnterWorkdirTool(),
        ExitWorkdirTool(),
        # Phase 10 — special
        SleepTool(),
        SyntheticOutputTool(),
        # Phase 10 — config
        ConfigTool(),
        # Phase 10 — interactive(CLI 用 stdin asker)
        AskUserQuestionTool(asker=make_stdin_asker()),
        # Phase 10 — notebook
        NotebookEditTool(),
        # Phase 10 — task
        TaskCreateTool(),
        TaskGetTool(),
        TaskListTool(),
        TaskUpdateTool(),
        TaskStopTool(),
        TaskOutputTool(),
        # Phase 10 — cron
        CronCreateTool(),
        CronListTool(),
        CronDeleteTool(),
    ]
    # ToolSearch 拿 self-aware 全清單(deferred 機制 — 模型可動態載 schema)
    base.append(ToolSearchTool(all_tools=base))
    return base


@app.command()
def serve(
    host: Annotated[
        str, typer.Option("--host", help="Bind address (default 127.0.0.1).")
    ] = "127.0.0.1",
    port: Annotated[
        int, typer.Option("--port", help="Listen port (default 8000).")
    ] = 8000,
    reload: Annotated[
        bool, typer.Option("--reload", help="Auto-reload on code change (dev).")
    ] = False,
    db_url: Annotated[
        str | None,
        typer.Option(
            "--db-url",
            help=(
                "Database URL(等同設 ORION_DB_URL),"
                "如 postgresql+asyncpg://... 或 sqlite+aiosqlite:///./orion.db。"
                "未設 → in-memory SessionManager(Phase 6 行為)。"
            ),
        ),
    ] = None,
) -> None:
    """Phase 6:啟 FastAPI server(uvicorn)。Phase 7 加 --db-url。

    `orion serve --port 8000` → `http://127.0.0.1:8000/healthz`
    WebSocket: `ws://127.0.0.1:8000/chat/stream/<session_id>?token=<jwt>`
    """
    import os

    import uvicorn

    if db_url:
        os.environ["ORION_DB_URL"] = db_url

    uvicorn.run(
        "orion_agent.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def run(
    prompt: Annotated[str, typer.Argument(help="User prompt to send to the model.")],
    provider: Annotated[
        str, typer.Option("--provider", "-p", help="anthropic | openai")
    ] = "anthropic",
    model: Annotated[
        str, typer.Option("--model", "-m", help="Model id.")
    ] = "claude-sonnet-4-6",
    max_turns: Annotated[
        int, typer.Option(help="Max agent turns before forced terminate.")
    ] = 30,
    max_tokens: Annotated[
        int, typer.Option(help="Max output tokens per turn.")
    ] = 4096,
    resume_id: Annotated[
        str | None,
        typer.Option(
            "--resume",
            help="Resume an existing session by ID (UUID). state_messages 會從 transcript 重建。",
        ),
    ] = None,
    no_persistence: Annotated[
        bool,
        typer.Option(
            "--no-persistence",
            help="Disable transcript / replacement-state persistence (in-memory only).",
        ),
    ] = False,
    user_id: Annotated[
        str,
        typer.Option(
            "--user-id",
            help="Memory key,預設 'default'(也可由 ORION_USER_ID 環境變數覆蓋)。",
        ),
    ] = "",
    no_memory: Annotated[
        bool,
        typer.Option(
            "--no-memory",
            help="Disable memory load + auto-extract (Phase 3 features).",
        ),
    ] = False,
    mcp_config: Annotated[
        str | None,
        typer.Option(
            "--mcp-config",
            help="額外 mcp.json 路徑(優先於 ~/.orion/mcp.json + cwd/.orion/mcp.json)。",
        ),
    ] = None,
    no_mcp: Annotated[
        bool,
        typer.Option(
            "--no-mcp",
            help="Disable MCP servers entirely (Phase 5)。",
        ),
    ] = False,
    sandbox: Annotated[
        str,
        typer.Option(
            "--sandbox",
            help="Sandbox backend: local | docker(預設 local;Phase 7)。",
        ),
    ] = "local",
) -> None:
    """跑完整 agent loop:多 turn、tool feedback、streaming。

    Phase 2:預設啟用 transcript JSONL 寫入(~/.orion/sessions/<id>/transcript.jsonl)。
    Phase 3:預設啟用 per-user memory + autoCompact。
    `--resume <id>` 從先前 session 載入歷史繼續對話。
    """
    from orion_agent.memory.paths import default_user_id as _default_uid

    effective_uid = user_id or _default_uid()

    asyncio.run(
        _run_async(
            prompt=prompt,
            provider=provider,
            model=model,
            max_turns=max_turns,
            max_tokens=max_tokens,
            resume_id=resume_id,
            no_persistence=no_persistence,
            user_id=effective_uid,
            no_memory=no_memory,
            mcp_config=mcp_config,
            no_mcp=no_mcp,
            sandbox=sandbox,
        )
    )


async def _run_async(
    *,
    prompt: str,
    provider: str,
    model: str,
    max_turns: int,
    max_tokens: int,
    resume_id: str | None = None,
    no_persistence: bool = False,
    user_id: str = "default",
    no_memory: bool = False,
    mcp_config: str | None = None,
    no_mcp: bool = False,
    sandbox: str = "local",
) -> None:
    from contextlib import AsyncExitStack
    from pathlib import Path
    from uuid import UUID

    from orion_agent.mcp.manager import McpManager
    from orion_agent.sandbox.factory import get_sandbox_backend
    from orion_agent.sandbox.proxy_tools import build_sandboxed_tools

    ctx = AgentContext(feature_flags=load_feature_flags(), user_id=user_id)
    llm = get_provider(provider, model)

    # ─── Phase 7:選 sandbox backend ───────────────────────────────────
    sandbox_backend = None
    sandboxed_tools_list: list[Any] = []
    if sandbox != "local":
        try:
            sandbox_backend = get_sandbox_backend(sandbox)
            sandboxed_tools_list = build_sandboxed_tools(sandbox_backend)
            print(f"[sandbox] using {sandbox} backend", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[sandbox] failed to init {sandbox!r}: {e}", flush=True)
            sandbox_backend = None

    async with AsyncExitStack() as stack:
        # ─── Phase 5:啟動 McpManager(若有 config 或啟用)─────────────────
        mcp_manager: McpManager | None = None
        if not no_mcp:
            extra_path = Path(mcp_config) if mcp_config else None
            manager = McpManager(extra_config_path=extra_path)
            if manager.configs:  # 有 config 才 connect,沒就跳過
                try:
                    mcp_manager = await stack.enter_async_context(manager)
                    if mcp_manager.connection_errors:
                        for name, err in mcp_manager.connection_errors.items():
                            print(
                                f"[mcp] {name!r} failed: {err}",
                                flush=True,
                            )
                    if mcp_manager.connected_servers:
                        print(
                            f"[mcp] connected: "
                            f"{', '.join(mcp_manager.connected_servers)} "
                            f"({len(mcp_manager.tools)} tools)",
                            flush=True,
                        )
                except Exception as e:  # noqa: BLE001
                    print(f"[mcp] initialization failed: {e}", flush=True)
                    mcp_manager = None

        # Phase 7:tools 用 sandboxed 版本(若 backend 啟用)
        effective_tools = sandboxed_tools_list if sandbox_backend is not None else _build_tools()

        if resume_id is not None:
            try:
                sid = UUID(resume_id)
            except ValueError:
                print(f"invalid session id (not a UUID): {resume_id!r}", flush=True)
                return
            conv = await Conversation.resume(
                sid,
                provider=llm,
                tools=effective_tools,
                max_turns=max_turns,
            )
            conv.persistence_enabled = not no_persistence
            conv.user_id = user_id
            conv.memory_enabled = not no_memory
            conv.auto_extract_memories = not no_memory
            conv.mcp_manager = mcp_manager
            conv.sandbox_backend = sandbox_backend
            print(
                f"=== resumed session {sid} (user={user_id}, "
                f"{len(conv.state_messages)} prior messages) ===",
                flush=True,
            )
        else:
            conv = Conversation(
                provider=llm,
                tools=effective_tools,
                max_turns=max_turns,
                max_tokens_per_turn=max_tokens,
                persistence_enabled=not no_persistence,
                user_id=user_id,
                memory_enabled=not no_memory,
                auto_extract_memories=not no_memory,
                mcp_manager=mcp_manager,
                sandbox_backend=sandbox_backend,
            )
            print(
                f"=== orion-agent ({provider} / {model}) "
                f"session={conv.session_id} ===",
                flush=True,
            )

        try:
            async for ev in conv.send(prompt, ctx=ctx):
                _render(ev)
        finally:
            # Phase 7:sandbox backend cleanup(如 Docker container)
            if sandbox_backend is not None:
                try:
                    await sandbox_backend.cleanup()
                except Exception as e:  # noqa: BLE001
                    print(f"[sandbox] cleanup error: {e}", flush=True)

        print(
            f"\n=== done — turns={conv.stats.turns}, "
            f"tools={conv.stats.tool_calls}({conv.stats.tool_errors} errors), "
            f"in={conv.stats.input_tokens}, out={conv.stats.output_tokens} ===",
            flush=True,
        )


def _render(ev: Any) -> None:
    """把 LoopEvent / ToolUpdate 印給 user 看。"""
    if isinstance(ev, AssistantTextDelta):
        sys.stdout.write(ev.text)
        sys.stdout.flush()
    elif isinstance(ev, AssistantThinkingDelta):
        # 暗灰色 reasoning
        sys.stdout.write(f"\x1b[2m{ev.text}\x1b[0m")
        sys.stdout.flush()
    elif isinstance(ev, AssistantTurnComplete):
        # turn 結束換行
        sys.stdout.write("\n")
        sys.stdout.flush()
    elif isinstance(ev, ToolProgressUpdate):
        # 工具中間事件:tool 啟動 / 進度 / 錯誤
        if isinstance(ev.event, TextEvent):
            # 工具的 final text 由 ToolResultUpdate 顯示,這裡跳過
            pass
        elif isinstance(ev.event, ProgressEvent):
            print(f"  [\x1b[2m{ev.tool_name} progress\x1b[0m] {ev.event.data}", flush=True)
        elif isinstance(ev.event, ErrorEvent):
            print(f"  [\x1b[31m{ev.tool_name} error\x1b[0m] {ev.event.message}", flush=True)
    elif isinstance(ev, ToolResultUpdate):
        marker = "\x1b[31m✗\x1b[0m" if ev.is_error else "\x1b[32m✓\x1b[0m"
        # 印 tool 的縮排結果摘要(前 500 字)
        first_block = ev.message.content[0] if isinstance(ev.message.content, list) else None
        text = ""
        if first_block is not None and hasattr(first_block, "content"):
            raw = first_block.content
            text = raw if isinstance(raw, str) else str(raw)
        preview = text if len(text) <= 500 else text[:500] + f"\n... [+{len(text) - 500} chars]"
        indented = "\n".join(f"    {line}" for line in preview.split("\n"))
        print(f"\n  {marker} {ev.tool_name} (id={ev.tool_use_id}):", flush=True)
        print(indented, flush=True)
    elif isinstance(ev, LoopTerminated):
        print(
            f"\n--- loop terminated: {ev.transition.reason} "
            f"(turns={ev.total_turns}) ---",
            flush=True,
        )


def cli() -> None:
    """pyproject.toml 指向的 entrypoint。"""
    app()


if __name__ == "__main__":
    cli()
