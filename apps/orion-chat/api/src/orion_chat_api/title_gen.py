"""對話標題自動生成 — 首輪後跑一個 mini-model side-query。

對齊 Cowork 的 `_generate_title`。用 mini model(成本控制,見偏好設定),
prompt 要求「同對話語言、3-6 字、純標題」。任何失敗回 None,呼叫端吞掉
(標題生成永遠不該影響對話本身)。
"""

from __future__ import annotations

from orion_model.catalog import validate
from orion_model.events import MessageStopEvent, TextDeltaEvent
from orion_model.provider import LLMProvider, get_provider
from orion_model.types import NormalizedMessage

from orion_sdk.telemetry.instrumentation import record_usage


def _record_side_query(
    provider: LLMProvider,
    ev: MessageStopEvent,
    *,
    session_id: str | None,
    user_id: str | None,
    origin: str,
) -> None:
    """把 side-query(title / follow_ups)的 usage 記進該 session 的 cost tracker,
    歸到對應 origin —— 否則這些 mini-model 呼叫的成本完全沒被算到(空殼)。"""
    if session_id is None:
        return
    u = ev.usage
    record_usage(
        session_id=session_id,
        user_id=user_id,
        model=provider.model,
        origin=origin,
        input_tokens=u.input_tokens,
        output_tokens=u.output_tokens,
        cache_read_tokens=u.cache_read_tokens,
        cache_creation_tokens=u.cache_creation_tokens,
    )

# provider → 該家的 mini model(catalog 內;不在則 fallback 原 provider)
_MINI_MODEL: dict[str, str] = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-5-mini",
    "google": "gemini-3.1-flash-lite",
}


def mini_provider_for(base: LLMProvider) -> LLMProvider:
    """回 base provider 對應的 mini model provider;無對應 / 建立失敗則回 base。"""
    mini = _MINI_MODEL.get(base.name)
    if mini and validate(base.name, mini):
        try:
            return get_provider(base.name, mini)
        except Exception:  # noqa: BLE001 — 任何建立失敗都 fallback
            return base
    return base


_TITLE_SYSTEM = "You generate concise conversation titles."
_TITLE_PROMPT = (
    "Summarise the conversation below as a short title of 3-6 words, in the "
    "same language as the conversation. Output ONLY the title — no quotes, no "
    "trailing punctuation, no preamble.\n\n"
    "User: {user}\nAssistant: {assistant}"
)


async def generate_session_title(
    provider: LLMProvider,
    user_text: str,
    assistant_text: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
) -> str | None:
    """跑一次 side-query 生標題。失敗 / 空字串回 None。成本歸 origin="title"。"""
    prompt = _TITLE_PROMPT.format(
        user=user_text[:2000], assistant=assistant_text[:2000],
    )
    # gpt-5 family 規則:不帶 temperature、max_tokens≥1024、reasoning_effort="minimal"
    kwargs: dict[str, object] = {"max_tokens": 1024}
    if provider.name == "openai":
        kwargs["reasoning_effort"] = "minimal"

    parts: list[str] = []
    try:
        async for ev in provider.stream(
            system=_TITLE_SYSTEM,
            messages=[NormalizedMessage(role="user", content=prompt)],
            **kwargs,  # type: ignore[arg-type]
        ):
            if isinstance(ev, TextDeltaEvent):
                parts.append(ev.text)
            elif isinstance(ev, MessageStopEvent):
                _record_side_query(
                    provider, ev,
                    session_id=session_id, user_id=user_id, origin="title",
                )
    except Exception:  # noqa: BLE001 — 標題生成失敗不可影響對話
        return None

    title = "".join(parts).strip().strip('"').strip()
    title = title.split("\n", 1)[0].strip()[:80]
    return title or None


_FOLLOWUP_SYSTEM = "You suggest concise follow-up questions a user might ask next."
_FOLLOWUP_PROMPT = (
    "Based on the conversation below, suggest 3 short follow-up questions the "
    "user might ask next, in the same language as the conversation. One per "
    "line, no numbering, no quotes.\n\nUser: {user}\nAssistant: {assistant}"
)


async def generate_followups(
    provider: LLMProvider,
    user_text: str,
    assistant_text: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
) -> list[str]:
    """跑 side-query 產最多 3 句 follow-up 建議。失敗回 []。成本歸 origin="follow_ups"。"""
    prompt = _FOLLOWUP_PROMPT.format(
        user=user_text[:2000], assistant=assistant_text[:2000],
    )
    kwargs: dict[str, object] = {"max_tokens": 1024}
    if provider.name == "openai":
        kwargs["reasoning_effort"] = "minimal"
    parts: list[str] = []
    try:
        async for ev in provider.stream(
            system=_FOLLOWUP_SYSTEM,
            messages=[NormalizedMessage(role="user", content=prompt)],
            **kwargs,  # type: ignore[arg-type]
        ):
            if isinstance(ev, TextDeltaEvent):
                parts.append(ev.text)
            elif isinstance(ev, MessageStopEvent):
                _record_side_query(
                    provider, ev,
                    session_id=session_id, user_id=user_id, origin="follow_ups",
                )
    except Exception:  # noqa: BLE001
        return []
    lines = [
        ln.strip().lstrip("-*0123456789. ").strip().strip('"')
        for ln in "".join(parts).splitlines()
    ]
    return [ln for ln in lines if ln][:3]
