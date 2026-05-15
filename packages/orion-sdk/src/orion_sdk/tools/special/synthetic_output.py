"""SyntheticOutputTool — Phase 10。對應 TS SyntheticOutputTool / hookHelpers structured output。

這支工具的存在純粹是給模型一個「我要回結構化資料」的指示。Caller 把 JSON Schema
塞到 input_schema,模型 emit tool_use 等同回符合 schema 的 JSON。

用法(SDK structured output 強制):
- caller 動態建 SyntheticOutputTool(schema=user_schema)
- conversation.tools = [SyntheticOutputTool(...)]
- 加 system prompt:"You MUST end by calling SyntheticOutput with the result."
- 模型呼叫 → 解析 input → 即是 caller 要的結構化結果

跟一般 tool 不同:
- 不執行 side effect(只是 echo input 回去 + record)
- caller 負責從 ctx 拿取最後一次 SyntheticOutput tool_input
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import TextEvent, ToolEvent, ToolInput


class SyntheticOutputInput(ToolInput):
    """Default schema(無自訂 schema 時的 fallback);caller 通常會 override `input_schema`。"""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")
    """allow extra:caller 動態 schema 可帶任意欄位。"""


class SyntheticOutputTool:
    name = "SyntheticOutput"
    description = (
        "Emit structured output. Call this exactly once with your final answer "
        "as a JSON object that matches the provided schema."
    )
    input_schema: type[BaseModel] = SyntheticOutputInput

    def __init__(self, schema: type[BaseModel] | None = None) -> None:
        if schema is not None:
            self.input_schema = schema
        self.last_output: dict[str, Any] | None = None
        """最後一次 model emit 的 input(caller 從這裡拿結果)。"""

    async def call(
        self,
        input: BaseModel,
        ctx: AgentContext,  # noqa: ARG002
    ) -> AsyncIterator[ToolEvent]:
        self.last_output = input.model_dump()
        # echo 回去當 tool result(模型看了知道已收到)
        yield TextEvent(text="(structured output recorded)")

    def is_concurrency_safe(self, input: BaseModel) -> bool:  # noqa: ARG002
        return False  # 寫 self.last_output

    def is_read_only(self, input: BaseModel) -> bool:  # noqa: ARG002
        return True

    def max_result_size_chars(self) -> int | float:
        return 1_000
