"""Real-API integration:多模態(text + image)是否能透過 SDK 真實傳到模型。

兩個 test:Anthropic Claude + OpenAI gpt-4o-mini,都送一張紅色純色 PNG
要模型描述。如果壞掉,模型回答不會提到 "red" / "色" 之類。

驗證的是 Conversation.send(prompt, images=[ImageBlock]) 一路到 provider 的
完整路徑;這是 Cowork attachment upload 的核心 contract。
"""

from __future__ import annotations

import base64
import io
import os

import pytest

from orion_model.provider import get_provider
from orion_model.types import ImageBlock
from orion_sdk.core.conversation import Conversation
from orion_sdk.core.query_loop import AssistantTextDelta, LoopTerminated


def _red_png_base64() -> str:
    """產一張 64x64 純紅 PNG → base64。沒裝 Pillow → skip。"""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        pytest.skip("Pillow not installed")
    img = Image.new("RGB", (64, 64), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
@pytest.mark.asyncio
async def test_anthropic_vision_sees_red_image() -> None:
    provider = get_provider("anthropic", "claude-sonnet-4-6")
    conv = Conversation(
        provider=provider,
        system_prompt="Describe images you see briefly.",
        tools=[],
        max_turns=1,
        persistence_enabled=False,
        memory_enabled=False,
    )
    image = ImageBlock(media_type="image/png", data=_red_png_base64())
    chunks: list[str] = []
    async for ev in conv.send(
        "What color is this image? Answer in one word.",
        images=[image],
    ):
        if isinstance(ev, AssistantTextDelta):
            chunks.append(ev.text)
        elif isinstance(ev, LoopTerminated):
            break
    answer = "".join(chunks).lower()
    assert "red" in answer, f"Anthropic vision failed — got: {answer!r}"


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)
@pytest.mark.asyncio
async def test_openai_vision_sees_red_image() -> None:
    """重點:Cowork 預設 default model 是 OpenAI gpt-4o-mini,vision 必須通。"""
    provider = get_provider("openai", "gpt-4o-mini")
    conv = Conversation(
        provider=provider,
        system_prompt="Describe images you see briefly.",
        tools=[],
        max_turns=1,
        persistence_enabled=False,
        memory_enabled=False,
    )
    image = ImageBlock(media_type="image/png", data=_red_png_base64())
    chunks: list[str] = []
    async for ev in conv.send(
        "What color is this image? Answer in one word.",
        images=[image],
    ):
        if isinstance(ev, AssistantTextDelta):
            chunks.append(ev.text)
        elif isinstance(ev, LoopTerminated):
            break
    answer = "".join(chunks).lower()
    assert "red" in answer, f"OpenAI vision failed — got: {answer!r}"
