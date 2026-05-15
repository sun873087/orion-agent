"""Skill / Plugin frontmatter 內宣告的 hook → 註冊到 HookRegistry。

範例 skill `~/.orion/skills/code-review.md`:

```markdown
---
name: code-review
description: Review code changes
hooks:
  - event: PreToolUse
    matcher: {tool_name: Edit}
    command: ./scripts/pre-edit-lint.sh
  - event: PostToolUse
    webhook: https://my-server/log
---

(skill body 略)
```

`register_frontmatter_hooks(hooks_list, registry)` 把 list 直接餵進 config_manager 的
build_handler,等同 settings.json hook,但來源不同(per-skill / per-plugin)。
"""

from __future__ import annotations

import logging
from typing import Any

from orion_sdk.hooks.config_manager import _build_handler
from orion_sdk.hooks.events import HOOK_EVENT_NAMES
from orion_sdk.hooks.registry import HookRegistry

logger = logging.getLogger(__name__)


def register_frontmatter_hooks(
    hooks_list: list[dict[str, Any]],
    registry: HookRegistry,
    *,
    web_only: bool = False,
    source: str | None = None,
) -> int:
    """把 frontmatter `hooks:` 欄位的條目註冊到 registry。

    每筆條目格式:
    ```
    {event: <HookEventName>, command|webhook: <...>, matcher: {...}, secret: <...>}
    ```

    Args:
        hooks_list: list of dict
        registry: 要註冊到的 HookRegistry
        web_only: True → 拒絕 shell command(只允許 webhook)
        source: 來源描述(skill name / plugin name),用於 log

    Returns:
        成功註冊的 hook 數。
    """
    if not isinstance(hooks_list, list):
        return 0

    count = 0
    for entry in hooks_list:
        if not isinstance(entry, dict):
            continue
        event_name = entry.get("event")
        if event_name not in HOOK_EVENT_NAMES:
            logger.warning(
                "frontmatter hook (%s) has unknown event %r",
                source or "?",
                event_name,
            )
            continue
        handler = _build_handler(entry, web_only=web_only)
        if handler is None:
            continue
        registry.register(event_name, handler)
        count += 1
    return count
