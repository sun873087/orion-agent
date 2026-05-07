"""Scan + load memory dir。

對應 spec § 5 scan.py。

格式約定:每個 .md 檔開頭 frontmatter:
    ---
    name: ...
    description: ...
    type: user|feedback|project|reference
    ---

只支援簡單 KEY: VALUE 一行格式 — **不**支援巢狀 / 多行 value / quoted strings(spec
不需要)。寫 mini parser 避免拉 pyyaml 依賴。

`MEMORY.md` index 不被 scan 當 memory(只是 user 寫的索引)— 但 update_index()
可由 caller(extract.py 寫新 memory 後)呼叫,維護該檔。
"""

from __future__ import annotations

import re
from pathlib import Path

from orion_agent.memory.paths import MemoryPaths
from orion_agent.memory.types import (
    Memory,
    MemoryFrontmatter,
    MemoryIndex,
    MemoryType,
)

_FRONTMATTER_PATTERN = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL,
)
"""配對開頭 ---\n...\n---\n + 後續 body。"""


def parse_frontmatter(text: str) -> tuple[MemoryFrontmatter | None, str]:
    """嘗試解析 .md 檔開頭 frontmatter。

    Returns:
        (frontmatter, body):若無 frontmatter,frontmatter=None,body=整檔 text
    """
    m = _FRONTMATTER_PATTERN.match(text)
    if not m:
        return None, text

    raw_fm = m.group(1)
    body = m.group(2)

    # KEY: VALUE 一行一個
    fields: dict[str, str] = {}
    for line in raw_fm.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()

    name = fields.get("name", "")
    description = fields.get("description", "")
    type_raw = fields.get("type", "")

    if not name or not description:
        # 缺必要欄位 → 視為無效 frontmatter
        return None, text

    mtype: MemoryType | None = None
    if type_raw:
        try:
            mtype = MemoryType(type_raw.lower())
        except ValueError:
            mtype = None  # 未知 type 視為 None,不 raise

    return MemoryFrontmatter(name=name, description=description, type=mtype), body


def load_memory_file(path: Path) -> Memory | None:
    """單檔載入。frontmatter 缺 / 損壞 → None。"""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    fm, body = parse_frontmatter(text)
    if fm is None:
        return None
    return Memory(frontmatter=fm, body=body, file_path=path)


def scan_memory_dir(paths: MemoryPaths) -> MemoryIndex:
    """掃 memory dir 載入所有 valid .md。

    跳過:
    - MEMORY.md(index 檔本身)
    - 沒 frontmatter / 損壞
    - 隱藏檔(.開頭)

    Returns:
        MemoryIndex 含所有 valid Memory 物件。
    """
    index = MemoryIndex()
    if not paths.memory_dir.exists() or not paths.memory_dir.is_dir():
        return index

    for p in sorted(paths.memory_dir.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        if p.name.startswith("."):
            continue
        m = load_memory_file(p)
        if m is not None:
            index.memories.append(m)
    return index


# ─── MEMORY.md index 維護 ──────────────────────────────────────────────────


def render_index(memories: list[Memory]) -> str:
    """Memory list → MEMORY.md content。

    Format(per spec):
      - [Title](file.md) — one-line description
    """
    lines = []
    # 按 type 分群:user / feedback / project / reference / others
    grouped: dict[str, list[Memory]] = {}
    for m in memories:
        key = m.type.value if m.type else "other"
        grouped.setdefault(key, []).append(m)

    order = ["user", "feedback", "project", "reference", "other"]
    for key in order:
        items = grouped.get(key, [])
        if not items:
            continue
        lines.append(f"## {key.capitalize()}")
        lines.append("")
        for m in sorted(items, key=lambda x: x.name):
            lines.append(f"- [{m.name}]({m.filename}) — {m.description}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_index(paths: MemoryPaths, memories: list[Memory]) -> None:
    """重寫 MEMORY.md。"""
    paths.ensure_dirs()
    paths.index.write_text(render_index(memories), encoding="utf-8")
