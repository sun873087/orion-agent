"""Input pipeline 主協調 — Phase 11。對應 TS processUserInput.ts。

把 raw input(可能是純字串,或 dict 含 text + images / attachments)
轉成事件序列,讓 Conversation.submit_raw_input 處理:

- `UserMessageEvent`:真正進 query loop 的訊息(可能是 str 或 ContentBlock list)
- `CommandResultEvent`:純顯示給 user(不送 API)
- `CommandInjectEvent`:注入下次 system prompt(/memory 之類)
- `ErrorEvent`:處理失敗(未知命令、無效 input 等)

Phase 11 範圍 web-chat 精簡:
- ✅ slash 解析 → registry dispatch
- ✅ image attachments(base64 → ContentBlock)
- ✅ uploaded file attachments(透過 upload_id 引用)
- ❌ `!shell` / `@file ref`(留 Phase 11c)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from orion_agent.commands.registry import get_command
from orion_agent.input.slash import is_slash_command, parse_slash


@dataclass
class UserMessageEvent:
    type: Literal["user_message"] = "user_message"
    content: str | list[dict[str, Any]] = ""
    """str(純文字)或 list[ContentBlock dict](含 image / 多區塊)"""


@dataclass
class CommandResultEvent:
    type: Literal["command_result"] = "command_result"
    text: str = ""
    side_effect: str | None = None


@dataclass
class CommandInjectEvent:
    type: Literal["command_inject"] = "command_inject"
    prompt: str = ""


@dataclass
class InputErrorEvent:
    type: Literal["error"] = "error"
    message: str = ""


InputEvent = (
    UserMessageEvent | CommandResultEvent | CommandInjectEvent | InputErrorEvent
)


@dataclass
class ImageAttachment:
    """base64-encoded image。"""

    media_type: str
    """例:`image/png` / `image/jpeg`。"""

    data: str
    """base64 encoded(不含 prefix)。"""


@dataclass
class FileUploadRef:
    """已上傳檔案的引用(內容由 upload_id 回讀)。"""

    upload_id: str
    filename: str = ""


@dataclass
class RawInput:
    """process_user_input 接的多型 input。

    純文字直接傳 str(便利);多型 metadata(images / uploads)用 RawInput。
    """

    text: str = ""
    images: list[ImageAttachment] = field(default_factory=list)
    uploads: list[FileUploadRef] = field(default_factory=list)


async def process_user_input(
    raw: str | RawInput,
    ctx: Any,
    conversation: Any,
) -> AsyncIterator[InputEvent]:
    """把 raw input 轉為 InputEvent 序列。

    純 str → 直接當 text;RawInput → 拆 text + images + uploads。
    """
    if isinstance(raw, str):
        text = raw
        images: list[ImageAttachment] = []
        uploads: list[FileUploadRef] = []
    else:
        text = raw.text
        images = list(raw.images)
        uploads = list(raw.uploads)

    # 1. Slash 命令(只看 text)
    stripped = text.strip() if text else ""
    if stripped and is_slash_command(stripped):
        cmd_name, args = parse_slash(stripped)
        cmd = get_command(cmd_name)
        if cmd is None:
            yield InputErrorEvent(message=f"unknown command: /{cmd_name}")
            return
        try:
            result = await cmd.execute(args, ctx, conversation)
        except Exception as e:  # noqa: BLE001
            yield InputErrorEvent(
                message=f"/{cmd_name} failed: {type(e).__name__}: {e}",
            )
            return

        if result.text:
            yield CommandResultEvent(
                text=result.text, side_effect=result.side_effect,
            )
        if result.new_user_message:
            yield UserMessageEvent(content=result.new_user_message)
        if result.inject_into_prompt:
            yield CommandInjectEvent(prompt=result.inject_into_prompt)
        return

    # 2. 純文字(可能含 image / upload attachment)
    if not text and not images and not uploads:
        yield InputErrorEvent(message="empty input")
        return

    if not images and not uploads:
        yield UserMessageEvent(content=text)
        return

    # 有 attachments → 包成 ContentBlock list
    blocks: list[dict[str, Any]] = []

    # text 區塊(可選)+ upload 引用文字描述
    text_parts: list[str] = []
    if text:
        text_parts.append(text)
    for u in uploads:
        label = u.filename or u.upload_id
        text_parts.append(f"[Attached file: {label} (id: {u.upload_id})]")
    if text_parts:
        blocks.append({"type": "text", "text": "\n".join(text_parts)})

    # image 區塊
    for img in images:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.media_type,
                    "data": img.data,
                },
            },
        )

    yield UserMessageEvent(content=blocks)
