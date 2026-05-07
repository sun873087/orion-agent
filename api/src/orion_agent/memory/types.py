"""Memory 型別。

對應 spec doc § 4 模組架構 + frontmatter 設計。

每個 .md 檔頭有 YAML-style frontmatter(限定 3 行 dash):
    ---
    name: short title
    description: one-line summary
    type: user|feedback|project|reference
    ---

之後是 markdown 內容。Memory 是 dataclass 包這些。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    """4 類 memory(per spec)。"""

    USER = "user"
    """關於 user 本人的事實 / 偏好 / 知識。"""

    FEEDBACK = "feedback"
    """user 明確指示記住的工作習慣 / 規則。"""

    PROJECT = "project"
    """正在做的專案脈絡(deadline、architecture decision、stakeholder 等)。"""

    REFERENCE = "reference"
    """指向外部資源(Linear project、Slack channel、Grafana dashboard 等)。"""


class MemoryFrontmatter(BaseModel):
    """Memory .md 檔的 frontmatter。"""

    name: str = Field(..., description="Memory 標題(短)。")
    description: str = Field(..., description="一句話摘要 — relevance ranker 看這個決定相關性。")
    type: MemoryType | None = Field(
        default=None,
        description="memory 類別。缺省也可,但相關性下降。",
    )


@dataclass
class Memory:
    """完整 memory(frontmatter + body + 來源檔)。"""

    frontmatter: MemoryFrontmatter
    body: str
    """frontmatter 後的 markdown 內容。"""
    file_path: Path
    """原檔位置(供刪 / 改用)。"""

    @property
    def filename(self) -> str:
        return self.file_path.name

    @property
    def name(self) -> str:
        return self.frontmatter.name

    @property
    def description(self) -> str:
        return self.frontmatter.description

    @property
    def type(self) -> MemoryType | None:
        return self.frontmatter.type


@dataclass
class MemoryIndex:
    """所有 memory 的 in-memory index。scan() 後得到。"""

    memories: list[Memory] = field(default_factory=list)

    def by_filename(self, name: str) -> Memory | None:
        for m in self.memories:
            if m.filename == name:
                return m
        return None

    def by_type(self, t: MemoryType) -> list[Memory]:
        return [m for m in self.memories if m.type == t]

    def __len__(self) -> int:
        return len(self.memories)
