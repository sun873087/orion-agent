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
from orion_agent.tools.file.edit import FileEditTool  # noqa: E402
from orion_agent.tools.file.read import FileReadTool  # noqa: E402
from orion_agent.tools.file.write import FileWriteTool  # noqa: E402
from orion_agent.tools.search.glob import GlobTool  # noqa: E402
from orion_agent.tools.search.grep import GrepTool  # noqa: E402
from orion_agent.tools.shell.bash import BashTool  # noqa: E402
from orion_agent.tools.todo.todo_write import TodoWriteTool  # noqa: E402
from orion_agent.tools.web.fetch import WebFetchTool  # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True)


# Phase 4:system prompt 改由 Conversation 自己組(prompt/static_sections + 動態段)。
# 不再在 main.py 寫死 — Conversation(system_prompt="") 會走 assembler 路徑。


def _build_tools() -> list[Tool[Any]]:
    """註冊所有 Phase 1 內建工具。AgentTool 不放這(避免子 agent 自我遞迴)。"""
    return [
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
        WebFetchTool(),
        SkillTool(),
        TodoWriteTool(),
    ]


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
) -> None:
    from uuid import UUID

    ctx = AgentContext(feature_flags=load_feature_flags(), user_id=user_id)
    llm = get_provider(provider, model)

    if resume_id is not None:
        try:
            sid = UUID(resume_id)
        except ValueError:
            print(f"invalid session id (not a UUID): {resume_id!r}", flush=True)
            return
        conv = await Conversation.resume(
            sid,
            provider=llm,
            tools=_build_tools(),
            # system_prompt 留空 → Conversation 用 Phase 4 assembler 組
            max_turns=max_turns,
        )
        conv.persistence_enabled = not no_persistence
        conv.user_id = user_id
        conv.memory_enabled = not no_memory
        conv.auto_extract_memories = not no_memory
        print(
            f"=== resumed session {sid} (user={user_id}, "
            f"{len(conv.state_messages)} prior messages) ===",
            flush=True,
        )
    else:
        conv = Conversation(
            provider=llm,
            # system_prompt 留空 → Conversation 用 Phase 4 assembler 組
            tools=_build_tools(),
            max_turns=max_turns,
            max_tokens_per_turn=max_tokens,
            persistence_enabled=not no_persistence,
            user_id=user_id,
            memory_enabled=not no_memory,
            auto_extract_memories=not no_memory,
        )
        print(
            f"=== orion-agent ({provider} / {model}) "
            f"session={conv.session_id} ===",
            flush=True,
        )

    async for ev in conv.send(prompt, ctx=ctx):
        _render(ev)

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
