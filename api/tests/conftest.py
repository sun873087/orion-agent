"""共用 pytest fixtures。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.core.state import AgentContext


@pytest.fixture
def tmp_ctx(tmp_path: Path) -> AgentContext:
    """乾淨的 AgentContext,cwd 設為 tmp_path,適合工具測試。"""
    return AgentContext(cwd=tmp_path)


@pytest.fixture
def sample_text_file(tmp_path: Path) -> Path:
    """暫存目錄下建一個 5 行小檔。"""
    p = tmp_path / "sample.txt"
    p.write_text("alpha\nbeta\ngamma\ndelta\nepsilon\n", encoding="utf-8")
    return p
