"""從 settings.json 載入 hook → 註冊到 HookRegistry。

settings.json 範例:

```json
{
  "hooks": {
    "PreToolUse": [
      {"command": "/path/to/lint.sh", "matcher": {"tool_name": "Edit"}, "timeout_seconds": 5}
    ],
    "PostToolUse": [
      {"webhook": "https://user.example.com/hook", "secret": "xxx"}
    ]
  }
}
```

兩種 handler:
- **shell command**(CLI / 本機):subprocess + JSON over stdin/stdout,有 timeout
- **webhook**(Web chat / production):httpx POST,選 HMAC-SHA256 簽名

`load_hooks_from_settings` — 同時支援兩種(優先 webhook)。
`load_hooks_from_settings_for_web` — 只接受 webhook(拒絕 shell)。

回值轉換:
- shell stdout / webhook response body 是 JSON 字串 → 嘗試 parse
- 含 `abort: true` → 轉 PreToolUseResult / UserPromptSubmitResult
- 否則回 None
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from orion_sdk.hooks.events import (
    HOOK_EVENT_NAMES,
    HookEvent,
    PreToolUseResult,
    UserPromptSubmitResult,
)
from orion_sdk.hooks.registry import HookRegistry

logger = logging.getLogger(__name__)


_DEFAULT_SHELL_TIMEOUT = 5.0
_DEFAULT_WEBHOOK_TIMEOUT = 5.0


HookHandler = Callable[[HookEvent], Awaitable[Any]]


def load_hooks_from_settings(
    settings: dict[str, Any],
    registry: HookRegistry,
    *,
    web_only: bool = False,
) -> int:
    """讀 settings,把每個 hook 註冊到 registry。

    Args:
        settings: 整個 settings dict(含 `hooks` 欄位)
        registry: 要註冊到的 HookRegistry
        web_only: True 時拒絕 shell command hook(只允許 webhook)

    Returns:
        成功註冊的 hook 數。
    """
    hooks_config = settings.get("hooks", {})
    if not isinstance(hooks_config, dict):
        return 0

    count = 0
    for event_name, hook_list in hooks_config.items():
        if event_name not in HOOK_EVENT_NAMES:
            logger.warning("unknown hook event %r in settings", event_name)
            continue
        if not isinstance(hook_list, list):
            continue
        for hook_def in hook_list:
            if not isinstance(hook_def, dict):
                continue
            handler = _build_handler(hook_def, web_only=web_only)
            if handler is None:
                continue
            registry.register(event_name, handler)
            count += 1
    return count


def load_hooks_from_settings_for_web(
    settings: dict[str, Any], registry: HookRegistry,
) -> int:
    """Web chat 模式 — 只接受 webhook,拒絕 shell。"""
    return load_hooks_from_settings(settings, registry, web_only=True)


def _build_handler(
    hook_def: dict[str, Any], *, web_only: bool,
) -> HookHandler | None:
    if "webhook" in hook_def:
        return _build_webhook_hook(hook_def)
    if "command" in hook_def:
        if web_only:
            logger.warning(
                "shell command hook rejected in web mode: %s", hook_def.get("command"),
            )
            return None
        return _build_shell_hook(hook_def)
    logger.warning("hook def missing 'webhook' or 'command': %r", hook_def)
    return None


# ─── Shell command handler ────────────────────────────────────────────────


def _build_shell_hook(hook_def: dict[str, Any]) -> HookHandler:
    """包 subprocess + stdin/stdout JSON,有 timeout。"""
    command = hook_def["command"]
    matcher = hook_def.get("matcher") or {}
    timeout = float(hook_def.get("timeout_seconds", _DEFAULT_SHELL_TIMEOUT))

    async def handler(event: HookEvent) -> Any:
        if not _matches(event, matcher):
            return None
        try:
            payload = json.dumps(event.to_serializable()).encode("utf-8")
        except (TypeError, ValueError) as e:
            logger.warning("hook event serialization failed: %s", e)
            return None

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            logger.warning("hook subprocess failed to start: %s", e)
            return None

        try:
            stdout_b, _stderr_b = await asyncio.wait_for(
                proc.communicate(input=payload), timeout=timeout,
            )
        except TimeoutError:
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            logger.warning("hook command timed out: %s", command)
            return None

        if proc.returncode != 0:
            return None
        return _parse_handler_result(event, stdout_b.decode("utf-8", errors="replace"))

    return handler


# ─── Webhook handler ──────────────────────────────────────────────────────


def _build_webhook_hook(hook_def: dict[str, Any]) -> HookHandler:
    """POST event JSON 到 user 設的 URL,timeout 5s。"""
    webhook_url = hook_def["webhook"]
    matcher = hook_def.get("matcher") or {}
    secret = hook_def.get("secret")
    timeout = float(hook_def.get("timeout_seconds", _DEFAULT_WEBHOOK_TIMEOUT))

    async def handler(event: HookEvent) -> Any:
        if not _matches(event, matcher):
            return None
        try:
            body = json.dumps(event.to_serializable())
        except (TypeError, ValueError) as e:
            logger.warning("hook event serialization failed: %s", e)
            return None

        headers = {"Content-Type": "application/json"}
        if secret:
            sig = hmac.new(
                secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256,
            ).hexdigest()
            headers["X-Orion-Signature"] = f"sha256={sig}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(webhook_url, content=body, headers=headers)
        except (httpx.TimeoutException, httpx.RequestError) as e:
            logger.warning("webhook %s failed: %s", webhook_url, e)
            return None

        if response.status_code != 200 or not response.text:
            return None
        return _parse_handler_result(event, response.text)

    return handler


# ─── Helpers ──────────────────────────────────────────────────────────────


def _matches(event: HookEvent, matcher: dict[str, Any]) -> bool:
    """簡易 matcher:支援 tool_name / user_id 過濾。"""
    if not matcher:
        return True
    expected_tool = matcher.get("tool_name")
    if expected_tool is not None:
        actual = getattr(event, "tool_name", None)
        if actual is None and getattr(event, "tool", None) is not None:
            actual = event.tool.name  # type: ignore[union-attr]
        if actual != expected_tool:
            return False
    expected_user = matcher.get("user_id")
    return not (expected_user is not None and getattr(event, "user_id", None) != expected_user)


def _parse_handler_result(event: HookEvent, text: str) -> Any:
    """把 hook 回的 JSON 字串轉成對應 Result 物件。

    - 空 / 解析失敗 → None
    - 有 `abort: true` → PreToolUseResult / UserPromptSubmitResult(看 event 型別)
    - 有 `modified_input` → PreToolUseResult
    - 有 `additional_context` → UserPromptSubmitResult
    - 其他 → None
    """
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    event_type = getattr(event, "type", None)
    abort = bool(data.get("abort", False))

    if event_type == "PreToolUse":
        if abort:
            return PreToolUseResult(
                abort=True, abort_reason=data.get("abort_reason"),
            )
        if "modified_input" in data:
            mi = data["modified_input"]
            if isinstance(mi, dict):
                return PreToolUseResult(modified_input=mi)
        return None

    if event_type == "UserPromptSubmit":
        if abort:
            return UserPromptSubmitResult(
                abort=True, abort_reason=data.get("abort_reason"),
            )
        ctx = data.get("additional_context")
        if isinstance(ctx, str) and ctx:
            return UserPromptSubmitResult(additional_context=ctx)
        return None

    return None
