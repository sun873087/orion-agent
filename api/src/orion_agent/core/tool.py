"""Tool Protocol — Python 版的 Tool 介面。

對應 TS Claude Code `src/Tool.ts`。Python 用 Protocol + Pydantic 取代 zod + buildTool。

用法:
  class FileReadTool:
      name = "Read"
      description = "Read a file"
      input_schema = FileReadInput  # 你的 Pydantic class

      async def call(self, input, ctx):
          yield TextEvent(text=...)

  isinstance(FileReadTool(), Tool)  # True (runtime_checkable)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from orion_agent.core.state import AgentContext


class ToolInput(BaseModel):
    """所有工具 input 的基類。Pydantic 自動產生 JSON Schema 給模型。"""

    model_config = {"extra": "forbid"}


class TextEvent(BaseModel):
    """工具產出文字結果。"""

    type: str = "text"
    text: str


class ProgressEvent(BaseModel):
    """工具進度事件(對應 TS ToolProgressData)。"""

    type: str = "progress"
    data: dict[str, Any]


class ErrorEvent(BaseModel):
    """工具錯誤。"""

    type: str = "error"
    message: str
    is_recoverable: bool = False


ToolEvent = TextEvent | ProgressEvent | ErrorEvent


Input_T = TypeVar("Input_T", bound=ToolInput)


@runtime_checkable
class Tool(Protocol[Input_T]):
    """Tool 介面。實作者要提供 name、input_schema、call 方法。

    可選覆寫:is_concurrency_safe / is_read_only / max_result_size_chars。
    對應 TS Tool interface(src/Tool.ts)。預設值都很保守。
    """

    name: str
    """模型看到的工具名稱(例 'Read')。"""

    input_schema: type[Input_T]
    """input 的 Pydantic 類別。"""

    description: str
    """給模型的工具說明。"""

    async def call(
        self,
        input: Input_T,
        ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        """執行工具,yield 事件。"""
        ...

    def is_concurrency_safe(self, input: Input_T) -> bool:
        """是否可與其他並發工具同時跑。預設 False(保守)。"""
        return False

    def is_read_only(self, input: Input_T) -> bool:
        """是否純讀。預設 False。"""
        return False

    def max_result_size_chars(self) -> int | float:
        """結果大小上限,超過要持久化(見 Phase 2)。預設 100_000。"""
        return 100_000
