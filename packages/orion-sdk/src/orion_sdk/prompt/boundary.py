"""Boundary marker — 切靜態段 vs 動態段。

對應 spec § 5 SYSTEM_PROMPT_DYNAMIC_BOUNDARY。

Anthropic provider 收到 `system: list[str]` 時,**最後一個 element 之前**的會被
標 cache_control: ephemeral(既有實作)。所以 boundary 就是「list 切兩段」
的位置。

assembler.build_system_prompt_list 直接回 `[<靜態合併>, <動態合併>]`,自然就是
boundary 在中間。本檔提供的 `split_at_boundary` 是給「單字串 + boundary marker」
場景的 helper(供 spec 對照測試)。
"""

from __future__ import annotations

SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "<<<ORION_DYNAMIC_BOUNDARY>>>"
"""若內嵌在單字串內,split_at_boundary 在此切。"""


def split_at_boundary(text: str) -> tuple[str, str]:
    """切單字串成 (static_part, dynamic_part)。

    沒找到 marker → (整段, "")。
    """
    if SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in text:
        return text, ""
    static_part, _, dynamic_part = text.partition(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
    return static_part.rstrip(), dynamic_part.lstrip()
