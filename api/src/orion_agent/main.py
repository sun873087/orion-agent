"""Phase 0 demo CLI。

跑法:
  orion --provider anthropic --model claude-sonnet-4-6 "Read /etc/hosts"
  orion --provider openai    --model gpt-5             "Read /etc/hosts"

Phase 0 範圍:單 turn streaming + tool 執行印結果。
**不**回填工具結果給模型再請求(那是 Phase 1 完整 agent loop)。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated

import typer
from dotenv import load_dotenv

# 載入 .env(若存在)— 把 ANTHROPIC_API_KEY / OPENAI_API_KEY 注入 process env。
# 必須在 import provider 之前,SDK client 在 import 時就會讀環境變數。
load_dotenv()

from orion_agent.core.state import AgentContext  # noqa: E402
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolInput  # noqa: E402
from orion_agent.llm.events import (  # noqa: E402
    MessageStopEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolUseStartEvent,
    ToolUseStopEvent,
)
from orion_agent.llm.provider import get_provider  # noqa: E402
from orion_agent.llm.tool_def import ToolDefinition  # noqa: E402
from orion_agent.llm.types import NormalizedMessage  # noqa: E402
from orion_agent.services.feature_flags import load_feature_flags  # noqa: E402
from orion_agent.tools.file.read import FileReadTool  # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def run(
    prompt: Annotated[str, typer.Argument(help="User prompt to send to the model.")],
    provider: Annotated[
        str, typer.Option("--provider", "-p", help="anthropic | openai")
    ] = "anthropic",
    model: Annotated[
        str, typer.Option("--model", "-m", help="Model id.")
    ] = "claude-sonnet-4-6",
    max_tokens: Annotated[int, typer.Option(help="Max output tokens.")] = 2048,
) -> None:
    """跑單 turn demo:streaming → 若 model 想 call Read 工具就執行印結果。"""
    asyncio.run(_run_async(prompt=prompt, provider=provider, model=model, max_tokens=max_tokens))


async def _run_async(*, prompt: str, provider: str, model: str, max_tokens: int) -> None:
    ctx = AgentContext(feature_flags=load_feature_flags())
    llm = get_provider(provider, model)

    file_read = FileReadTool()
    tool_defs = [
        ToolDefinition(
            name=file_read.name,
            description=file_read.description,
            input_schema=file_read.input_schema.model_json_schema(),
        )
    ]

    messages: list[NormalizedMessage] = [
        NormalizedMessage(role="user", content=prompt),
    ]

    system_prompt = (
        "You are a concise assistant. If the user asks you to read a file, "
        "use the Read tool with an absolute path. Otherwise just answer."
    )

    print(f"=== orion-agent ({provider} / {model}) ===", flush=True)

    pending_tool: ToolUseStopEvent | None = None

    async for event in llm.stream(
        system=system_prompt,
        messages=messages,
        tools=tool_defs,
        max_tokens=max_tokens,
    ):
        if isinstance(event, TextDeltaEvent):
            sys.stdout.write(event.text)
            sys.stdout.flush()
        elif isinstance(event, ThinkingDeltaEvent):
            sys.stdout.write(f"\x1b[2m{event.text}\x1b[0m")
            sys.stdout.flush()
        elif isinstance(event, ToolUseStartEvent):
            print(f"\n[tool_use_start] {event.tool_name} (id={event.tool_use_id})", flush=True)
        elif isinstance(event, ToolUseStopEvent):
            print(f"[tool_use_stop]  input={event.full_input}", flush=True)
            pending_tool = event
        elif isinstance(event, MessageStopEvent):
            print(
                f"\n[message_stop] reason={event.stop_reason} "
                f"in={event.usage.input_tokens} out={event.usage.output_tokens} "
                f"cache_read={event.usage.cache_read_tokens}",
                flush=True,
            )

    # Phase 0:單 turn,只執行第一個 tool_use 後停。Phase 1 才有完整 loop。
    if pending_tool is not None and pending_tool.tool_name == file_read.name:
        print("\n--- executing tool locally ---", flush=True)
        try:
            tool_input = file_read.input_schema.model_validate(pending_tool.full_input)
        except (ValueError, TypeError) as e:
            print(f"[tool input invalid] {e}", flush=True)
            return
        await _drain_tool(file_read, tool_input, ctx)


async def _drain_tool(tool: FileReadTool, tool_input: ToolInput, ctx: AgentContext) -> None:
    async for tool_event in tool.call(tool_input, ctx):  # type: ignore[arg-type]
        if isinstance(tool_event, TextEvent):
            print(tool_event.text)
        elif isinstance(tool_event, ErrorEvent):
            print(f"[tool error] {tool_event.message}")


def cli() -> None:
    """pyproject.toml 指向的 entrypoint。"""
    app()


if __name__ == "__main__":
    cli()
