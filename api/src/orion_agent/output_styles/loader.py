"""Output style loader。Phase 13。對應 TS `outputStyles/loadOutputStylesDir.ts`。

Output style = markdown 檔 + YAML frontmatter:
  - frontmatter `name`(預設用檔名 stem)
  - frontmatter `description`(列在 `/output-style` 命令時顯示)
  - body = 真正注入 system prompt 的 prompt 內容

Sources(後者覆蓋前者,last-wins):
  1. `$ORION_HOME/output-styles/`
  2. `<cwd>/.orion/output-styles/`

設計上不 cache(每次 lookup 都重 walk dir);Phase 13 範圍 user 量 / 檔數都小,夠用。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 64 * 1024


@dataclass(frozen=True)
class OutputStyle:
    name: str
    description: str
    prompt: str
    """markdown body — 注入 system prompt 的內容。"""

    source_path: Path | None = None
    keep_coding_instructions: bool = True
    """True → 加在預設 prompt 後;False → 替代預設(Phase 13 caller 預設皆 True)。"""


def _orion_home() -> Path:
    base = os.environ.get("ORION_HOME") or str(Path.home() / ".orion")
    return Path(base)


def _default_dirs(cwd: Path | None = None) -> list[Path]:
    cwd = cwd or Path.cwd()
    return [
        _orion_home() / "output-styles",
        cwd / ".orion" / "output-styles",
    ]


def load_output_styles_dir(directory: Path) -> list[OutputStyle]:
    """掃單一目錄,parse 所有 `*.md` 為 OutputStyle。

    缺檔 / 損壞 frontmatter / 過大 → log + 略過(不 raise)。
    """
    if not directory.exists() or not directory.is_dir():
        return []

    out: list[OutputStyle] = []
    for md_path in sorted(directory.glob("*.md")):
        if not md_path.is_file():
            continue
        try:
            size = md_path.stat().st_size
        except OSError:
            continue
        if size > _MAX_FILE_BYTES:
            logger.warning(
                "output style %s too large (%d bytes) — skipping",
                md_path, size,
            )
            continue
        try:
            post = frontmatter.load(md_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("failed to parse output style %s: %s", md_path, e)
            continue

        meta = post.metadata or {}
        name = str(meta.get("name") or md_path.stem)
        body = post.content or ""
        if not body.strip():
            # 空 prompt 沒意義,跳過
            continue
        out.append(
            OutputStyle(
                name=name,
                description=str(meta.get("description") or ""),
                prompt=body,
                source_path=md_path,
                keep_coding_instructions=bool(
                    meta.get("keep_coding_instructions", True),
                ),
            )
        )
    return out


def load_all_output_styles(cwd: Path | None = None) -> list[OutputStyle]:
    """從預設位置匯總。後加的目錄覆蓋前者(同 name 後者贏)。"""
    by_name: dict[str, OutputStyle] = {}
    for d in _default_dirs(cwd):
        for s in load_output_styles_dir(d):
            by_name[s.name] = s
    return list(by_name.values())


def find_output_style(
    name: str, *, cwd: Path | None = None,
) -> OutputStyle | None:
    """快取友善的單筆 lookup。"""
    if not name:
        return None
    for s in load_all_output_styles(cwd):
        if s.name == name:
            return s
    return None


def list_output_style_names(*, cwd: Path | None = None) -> list[str]:
    return sorted(s.name for s in load_all_output_styles(cwd))
