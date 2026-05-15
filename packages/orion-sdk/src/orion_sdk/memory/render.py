"""把選中的 memories 渲染成 system prompt 前綴。

對應 spec § 5 render.py。

格式:在 system prompt 開頭插入 `<memories>...</memories>` 區塊,模型可看見。
為了 prompt cache 穩定,**memories 排序固定**(by filename),不隨機。
"""

from __future__ import annotations

from orion_sdk.memory.types import Memory

_HEADER = """\
<memories>
The following are relevant long-term memories about the user, your past
collaboration, or the current project. Use them when applicable, but do not
mention them unless directly relevant.
"""

_FOOTER = "</memories>"


def render_memories(memories: list[Memory]) -> str:
    """選中的 memories → system prompt 區塊。

    若 memories 為空 → 回空字串(prefix 不加東西)。
    """
    if not memories:
        return ""

    parts = [_HEADER]
    for m in sorted(memories, key=lambda x: x.filename):
        type_str = f" [{m.type.value}]" if m.type else ""
        parts.append(f"\n## {m.name}{type_str}")
        parts.append(f"({m.description})")
        parts.append("")
        parts.append(m.body.strip())
        parts.append("")

    parts.append(_FOOTER)
    return "\n".join(parts)


def prepend_to_system_prompt(
    base_system_prompt: str, memories: list[Memory]
) -> str:
    """把 render_memories 結果接到 base system prompt 前面。"""
    rendered = render_memories(memories)
    if not rendered:
        return base_system_prompt
    return rendered + "\n\n" + base_system_prompt
