"""Memory extraction — 對話結束後讓 LLM 看一眼,決定要不要寫新 memory。

對應 spec § 5 extract.py(簡化:單次 LLM call,非 fork agent)。

由 Conversation.send() 在 LoopTerminated 時可選觸發。
失敗影響本對話 — 用 try/except 隔離,不 propagate。
"""

from __future__ import annotations

import re
from pathlib import Path

from orion_model.events import (
    MessageStopEvent,
    TextDeltaEvent,
)
from orion_model.provider import LLMProvider
from orion_model.types import (
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from orion_sdk.memory.extract_prompts import (
    EXTRACT_SYSTEM_PROMPT,
    build_extract_user_prompt,
)
from orion_sdk.memory.paths import MemoryPaths
from orion_sdk.memory.scan import (
    parse_frontmatter,
    write_index,
)
from orion_sdk.memory.types import Memory

_EXTRACT_BLOCK_PATTERN = re.compile(
    r"^(FILE|UPDATE):\s*(\S+)\s*\n(.*?)\nEND",
    re.DOTALL | re.MULTILINE,
)


def _summarize_conversation(messages: list[NormalizedMessage], *, max_chars: int = 8000) -> str:
    """把 conversation 攤平成 LLM 友善 summary(限長度)。"""
    lines: list[str] = []
    for m in messages:
        role = m.role
        if isinstance(m.content, str):
            lines.append(f"### {role}\n{m.content}\n")
        elif isinstance(m.content, list):
            for block in m.content:
                if isinstance(block, TextBlock):
                    lines.append(f"### {role}\n{block.text}\n")
                elif isinstance(block, ToolUseBlock):
                    lines.append(
                        f"### {role}\n[tool_use {block.name}({block.input})]\n"
                    )
                elif isinstance(block, ToolResultBlock):
                    content_str = (
                        block.content
                        if isinstance(block.content, str)
                        else str(block.content)
                    )
                    short = content_str[:300] + ("..." if len(content_str) > 300 else "")
                    lines.append(f"### {role}\n[tool_result] {short}\n")

    full = "\n".join(lines)
    if len(full) <= max_chars:
        return full
    # 取頭尾,中間略
    head = full[: max_chars // 2]
    tail = full[-max_chars // 2 :]
    return head + "\n\n... [middle truncated] ...\n\n" + tail


_BODY_PREVIEW_CHARS = 200


def _summarize_existing_memories(memories: list[Memory]) -> str:
    """把現有 memory 列成 LLM 看得懂的清單,附 body preview。

    每筆格式:
        - <filename> (<type>) <name>: <description>
            body preview: <first 200 chars, newlines collapsed>

    Filename 寫在前面讓 LLM 知道 `UPDATE: <filename>` 該填什麼。Body preview 讓 LLM
    判斷新發現是否真的跟既有 memory 重複(只看 description 容易誤判)。
    """
    if not memories:
        return ""
    lines = []
    for m in sorted(memories, key=lambda x: x.filename):
        type_str = m.type.value if m.type else "?"
        lines.append(f"- {m.filename} ({type_str}) {m.name}: {m.description}")
        preview = " ".join(m.body.split())  # collapse whitespace/newlines
        if preview:
            if len(preview) > _BODY_PREVIEW_CHARS:
                preview = preview[:_BODY_PREVIEW_CHARS] + "..."
            lines.append(f"    body preview: {preview}")
    return "\n".join(lines)


_VALID_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_-]+\.md$")


def _is_valid_memory_filename(name: str) -> bool:
    if not _VALID_FILENAME_RE.match(name):
        return False
    return name != "MEMORY.md"


async def _provider_complete(
    provider: LLMProvider, system: str, user_text: str
) -> str:
    chunks: list[str] = []
    messages = [NormalizedMessage(role="user", content=user_text)]
    async for ev in provider.stream(
        system=system,
        messages=messages,
        tools=[],
        max_tokens=4096,
    ):
        if isinstance(ev, TextDeltaEvent):
            chunks.append(ev.text)
        elif isinstance(ev, MessageStopEvent):
            break
    return "".join(chunks)


def parse_extract_output(text: str) -> list[tuple[str, str, str]]:
    """模型輸出 → list of (op, filename, full_content)。

    op 是 "create"(FILE 區塊)或 "update"(UPDATE 區塊)。
    """
    text = text.strip()
    if text == "NONE" or not text:
        return []

    out: list[tuple[str, str, str]] = []
    for m in _EXTRACT_BLOCK_PATTERN.finditer(text):
        verb = m.group(1).strip()
        filename = m.group(2).strip()
        content = m.group(3).strip()
        if not content.endswith("\n"):
            content += "\n"
        op = "update" if verb == "UPDATE" else "create"
        out.append((op, filename, content))
    return out


async def extract_memories(
    conversation_messages: list[NormalizedMessage],
    existing_memories: list[Memory],
    *,
    provider: LLMProvider,
    paths: MemoryPaths,
    overwrite: bool = False,
) -> list[Memory]:
    """跑萃取。失敗回空 list(不 raise)。

    Args:
        conversation_messages: 整段對話歷史
        existing_memories: 給 LLM 看,以決定 UPDATE vs FILE
        provider: LLM(任一 provider)
        paths: target memory dir
        overwrite: CREATE 時遇同檔名是否覆蓋(預設 False — 安全)。UPDATE 永遠 overwrite。

    Returns:
        異動的 Memory list(create + update,皆已寫進 disk)。MEMORY.md 也會被更新。
    """
    if not conversation_messages:
        return []

    paths.ensure_dirs()

    conv_summary = _summarize_conversation(conversation_messages)
    existing_summary = _summarize_existing_memories(existing_memories)
    user_text = build_extract_user_prompt(conv_summary, existing_summary)

    try:
        raw = await _provider_complete(provider, EXTRACT_SYSTEM_PROMPT, user_text)
    except Exception:  # noqa: BLE001 — 萃取失敗不該影響主對話
        return []

    blocks = parse_extract_output(raw)
    if not blocks:
        return []

    existing_by_filename = {m.filename: m for m in existing_memories}
    created: list[Memory] = []
    updated_by_filename: dict[str, Memory] = {}

    for op, filename, content in blocks:
        if not _is_valid_memory_filename(filename):
            continue

        target = paths.memory_file(filename)
        is_existing = target.exists()

        if op == "create":
            if is_existing and not overwrite:
                continue
        else:  # op == "update"
            # UPDATE 必須對應實際存在的檔案,否則 LLM 在編造 filename
            if not is_existing:
                continue

        fm, body = parse_frontmatter(content)
        if fm is None:
            continue

        try:
            target.write_text(content, encoding="utf-8")
        except OSError:
            continue

        mem = Memory(frontmatter=fm, body=body, file_path=target)
        if op == "create":
            # 同檔名 CREATE + overwrite 走到這 → 當成 update 處理(避免 index 重複)
            if filename in existing_by_filename:
                updated_by_filename[filename] = mem
            else:
                created.append(mem)
        else:
            updated_by_filename[filename] = mem

    if not created and not updated_by_filename:
        return []

    # 更新 MEMORY.md:被 update 的 entry 用新版本取代,其他保留,最後 append 新建
    final = [
        updated_by_filename.get(m.filename, m) for m in existing_memories
    ]
    final.extend(created)
    write_index(paths, final)

    return list(updated_by_filename.values()) + created


def _format_path(p: Path) -> str:
    """Helper for logging/display."""
    return str(p)
