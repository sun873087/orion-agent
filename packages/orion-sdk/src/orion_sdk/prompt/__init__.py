"""System prompt 組裝層。

對應 Phase 4 spec(`docs/phases/04-system-prompt.md`)。

設計:
- 7 段**靜態** + 5 段**動態**
- 靜態段被 cached(module-level dict),動態段每次重算
- assembler 把它們組成 `list[str]`(2 元素:靜態合併 + 動態合併)
- Anthropic provider 自動把 list 最後 element 之外的標 `cache_control: ephemeral`
  → 第 0 元素(靜態段)被 cache,第 1 元素(動態段)不 cache
- OpenAI provider 自動 cache 開頭 prefix > 1024 tokens(無需手動標記)
"""

from orion_sdk.prompt.assembler import (
    SystemPromptParts,
    build_system_prompt_list,
    fetch_system_prompt_parts,
)
from orion_sdk.prompt.boundary import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    split_at_boundary,
)
from orion_sdk.prompt.sections import (
    DANGEROUS_uncached,
    clear_section_cache,
    register_section,
    section_cache_size,
)

__all__ = [
    "DANGEROUS_uncached",
    "SYSTEM_PROMPT_DYNAMIC_BOUNDARY",
    "SystemPromptParts",
    "build_system_prompt_list",
    "clear_section_cache",
    "fetch_system_prompt_parts",
    "register_section",
    "section_cache_size",
    "split_at_boundary",
]
