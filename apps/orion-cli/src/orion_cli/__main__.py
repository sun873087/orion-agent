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

from pathlib import Path

import typer
from dotenv import load_dotenv

# 載入 per-app .env(apps/orion-cli/.env)— 注入 API keys。必須在 import
# provider 之前。不抓 project root .env;每 app 各自隔離 secret。
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from orion_sdk.core.conversation import Conversation  # noqa: E402
from orion_sdk.core.query_loop import (  # noqa: E402
    AssistantTextDelta,
    AssistantThinkingDelta,
    AssistantTurnComplete,
    LoopTerminated,
)
from orion_sdk.core.state import AgentContext  # noqa: E402
from orion_sdk.core.tool import ErrorEvent, ProgressEvent, TextEvent, Tool  # noqa: E402
from orion_sdk.core.tool_execution import (  # noqa: E402
    ToolProgressUpdate,
    ToolResultUpdate,
)
from orion_model.provider import get_provider  # noqa: E402
from orion_sdk.services.feature_flags import load_feature_flags  # noqa: E402
from orion_sdk.tools.interactive.ask_user import (  # noqa: E402
    make_stdin_asker,
)

app = typer.Typer(add_completion=False, no_args_is_help=True)


# Phase 4:system prompt 改由 Conversation 自己組(prompt/static_sections + 動態段)。
# 不再在 main.py 寫死 — Conversation(system_prompt="") 會走 assembler 路徑。


def _build_tools() -> list[Tool[Any]]:
    """CLI 註冊內建工具(用 stdin asker 給 AskUserQuestionTool)。

    CLI host-specific tools 透過 `extra_tools` 注入:
    - Cron*(apscheduler)— SDK 不背
    - Config — 寫 `~/.orion/settings.json`,Cowork 用 cowork_prefs / chat-api
      多租戶不該開放給 LLM,只 CLI 註冊

    Web chat 場景請改用 `tools.builtin_set.build_default_tool_set()`(無 asker、
    無 extra_tools)。
    """
    from orion_cli.config_tool import ConfigTool
    from orion_cli.cron_tools import build_cron_tools
    from orion_sdk.tools.builtin_set import build_default_tool_set
    return build_default_tool_set(
        asker=make_stdin_asker(),
        extra_tools=[*build_cron_tools(), ConfigTool()],
    )


# Phase 30-C:`orion serve` 移到 orion-chat-api package(`orion-chat-api serve`)
# CLI 殼不該 import uvicorn / fastapi。


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
    from orion_sdk.memory.paths import default_user_id as _default_uid

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


def _install_sigint_handler(ctx: AgentContext) -> None:
    """Phase 16:第一次 Ctrl-C → graceful abort;5 秒內第二次 → force exit。

    Linux/macOS only(用 asyncio add_signal_handler)。Windows fallback 用預設
    KeyboardInterrupt(asyncio 不支援 add_signal_handler)。
    """
    import os
    import signal
    import time

    last_press: dict[str, float] = {"t": 0.0}
    _DOUBLE_PRESS_WINDOW = 5.0

    def _handler() -> None:
        now = time.monotonic()
        if ctx.abort_event.is_set() and (now - last_press["t"]) < _DOUBLE_PRESS_WINDOW:
            # 第二次:強制終止
            print("\n[abort] force quit", flush=True)
            os._exit(130)  # 130 = 128 + SIGINT
        # 第一次:graceful
        last_press["t"] = now
        ctx.abort_event.set()
        print(
            "\n[abort] cancelling — press Ctrl-C again within "
            f"{int(_DOUBLE_PRESS_WINDOW)}s to force quit",
            flush=True,
        )

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _handler)
    except (NotImplementedError, RuntimeError):
        # Windows / 不支援的 platform:不裝 → 走預設 KeyboardInterrupt
        pass


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

    from orion_sdk.mcp.manager import McpManager
    from orion_sdk.sandbox.factory import get_sandbox_backend
    from orion_sdk.sandbox.proxy_tools import build_sandboxed_tools

    ctx = AgentContext(feature_flags=load_feature_flags(), user_id=user_id)
    _install_sigint_handler(ctx)
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
