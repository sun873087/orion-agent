"""從 upstream response 解出 token 使用量 + 算 cost。

支援 endpoint:
- /openai/v1/chat/completions stream(SSE last chunk usage)+ non-stream
- /openai/v1/responses 同上(Responses API wire 對齊)
- /openai/v1/embeddings non-stream usage
- /openai/v1/audio/speech request body 算 input chars × tts pricing
- /anthropic/v1/messages stream(message_delta 累加)+ non-stream

其他 endpoint 走 best-effort fallback:cost=0,只 log endpoint 名(讓 admin
看得到誰打了什麼,即使沒算到費用)。

Pricing 來源:`orion_model.catalog.get_pricing()` /
`orion_model.tts_catalog.get_tts_pricing()`(跨 host 共用同份 catalog)。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class UsageEvent:
    provider: str
    model: str
    endpoint: str
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    cost_usd: float


# ─── pricing lookup ───────────────────────────────────────────────────────


def _compute_cost(
    provider: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_tokens: int | None,
    cache_creation_tokens: int | None,
) -> float:
    """Cost per 1M tokens × token count。沒對應 pricing → 0(log warning)。"""
    from orion_model.catalog import get_pricing

    p = get_pricing(provider, model)
    if p is None:
        _log.warning("no pricing for %s / %s — cost=0", provider, model)
        return 0.0
    cost = 0.0
    # cached input 跟 fresh input 分開算
    fresh_input = (input_tokens or 0) - (cache_read_tokens or 0)
    if fresh_input < 0:
        fresh_input = 0
    cost += fresh_input * p.get("input", 0.0) / 1_000_000
    cost += (output_tokens or 0) * p.get("output", 0.0) / 1_000_000
    cost += (cache_read_tokens or 0) * p.get("cache_read", 0.0) / 1_000_000
    if cache_creation_tokens:
        cost += cache_creation_tokens * p.get("cache_creation", 0.0) / 1_000_000
    return round(cost, 8)


# ─── helpers ──────────────────────────────────────────────────────────────


def _try_json(b: bytes) -> dict[str, Any] | None:
    if not b:
        return None
    try:
        v = json.loads(b)
        return v if isinstance(v, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _iter_sse_data_lines(body: bytes):
    """SSE format:`data: <json>\\n\\n`(可能多筆),逐筆 yield json dict。"""
    text = body.decode("utf-8", errors="replace")
    for raw in text.split("\n\n"):
        # 每筆事件可能有多行(event:, data:, id:),只取 data:
        for line in raw.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue


# ─── per-endpoint parsers ─────────────────────────────────────────────────


def _parse_openai_chat_or_responses(
    request_body: bytes, response_body: bytes, content_type: str
) -> tuple[str | None, dict[str, int] | None]:
    """回 (model, usage_dict);usage_dict = {input_tokens, output_tokens,
    cache_read_tokens}。"""
    req = _try_json(request_body) or {}
    model = req.get("model") if isinstance(req.get("model"), str) else None

    # Non-stream:整個 response 是一份 JSON
    if "text/event-stream" not in content_type:
        resp = _try_json(response_body)
        if resp is None:
            return model, None
        if isinstance(resp.get("model"), str):
            model = resp["model"]
        usage = resp.get("usage")
        if not isinstance(usage, dict):
            return model, None
        # Chat completions 用 prompt_tokens / completion_tokens;Responses API
        # 用 input_tokens / output_tokens — 兩種都 normalize 進來
        prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        out = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        cache = 0
        details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        if isinstance(details, dict):
            cache = details.get("cached_tokens") or 0
        return model, {
            "input_tokens": int(prompt),
            "output_tokens": int(out),
            "cache_read_tokens": int(cache),
        }

    # Stream:翻最後一份 SSE chunk 找 usage(client 要設 stream_options.include_usage=true)
    last_usage: dict[str, Any] | None = None
    last_model = model
    for evt in _iter_sse_data_lines(response_body):
        if isinstance(evt.get("model"), str):
            last_model = evt["model"]
        u = evt.get("usage")
        if isinstance(u, dict):
            last_usage = u
    if last_usage is None:
        return last_model, None
    prompt = last_usage.get("prompt_tokens") or last_usage.get("input_tokens") or 0
    out = last_usage.get("completion_tokens") or last_usage.get("output_tokens") or 0
    cache = 0
    details = (
        last_usage.get("prompt_tokens_details")
        or last_usage.get("input_tokens_details")
        or {}
    )
    if isinstance(details, dict):
        cache = details.get("cached_tokens") or 0
    return last_model, {
        "input_tokens": int(prompt),
        "output_tokens": int(out),
        "cache_read_tokens": int(cache),
    }


def _parse_openai_embeddings(
    request_body: bytes, response_body: bytes
) -> tuple[str | None, dict[str, int] | None]:
    req = _try_json(request_body) or {}
    model = req.get("model") if isinstance(req.get("model"), str) else None
    resp = _try_json(response_body)
    if resp is None:
        return model, None
    if isinstance(resp.get("model"), str):
        model = resp["model"]
    usage = resp.get("usage")
    if not isinstance(usage, dict):
        return model, None
    return model, {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": 0,
        "cache_read_tokens": 0,
    }


def _parse_openai_audio_speech(
    request_body: bytes,
) -> tuple[str | None, int]:
    """Request body 帶 input text 跟 model。回 (model, char_count)。"""
    req = _try_json(request_body) or {}
    model = req.get("model") if isinstance(req.get("model"), str) else None
    input_str = req.get("input")
    char_count = len(input_str) if isinstance(input_str, str) else 0
    return model, char_count


def _parse_anthropic_messages(
    request_body: bytes, response_body: bytes, content_type: str
) -> tuple[str | None, dict[str, int] | None]:
    req = _try_json(request_body) or {}
    model = req.get("model") if isinstance(req.get("model"), str) else None

    if "text/event-stream" not in content_type:
        resp = _try_json(response_body)
        if resp is None:
            return model, None
        if isinstance(resp.get("model"), str):
            model = resp["model"]
        usage = resp.get("usage")
        if not isinstance(usage, dict):
            return model, None
        return model, {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_read_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "cache_creation_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        }

    # Stream:input_tokens 在 message_start.usage,output_tokens / cache 累加在
    # 後續 message_delta.usage(每筆 delta 給新的最新 output_tokens 值,不是 delta)。
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_creation = 0
    saw_model = False
    for evt in _iter_sse_data_lines(response_body):
        t = evt.get("type")
        if t == "message_start":
            msg = evt.get("message") or {}
            if isinstance(msg.get("model"), str):
                model = msg["model"]
                saw_model = True
            u = msg.get("usage") or {}
            if isinstance(u, dict):
                input_tokens = int(u.get("input_tokens") or 0)
                output_tokens = int(u.get("output_tokens") or 0)
                cache_read = int(u.get("cache_read_input_tokens") or 0)
                cache_creation = int(u.get("cache_creation_input_tokens") or 0)
        elif t == "message_delta":
            u = evt.get("usage") or {}
            if isinstance(u, dict):
                # message_delta 內 usage 給的是「累積到目前為止」的 output tokens,
                # 取最後一筆作 final。
                if "output_tokens" in u:
                    output_tokens = int(u["output_tokens"])

    if not saw_model and input_tokens == 0 and output_tokens == 0:
        return model, None
    return model, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
    }


# ─── dispatch ─────────────────────────────────────────────────────────────


_OPENAI_CHAT_PATHS = re.compile(r"^/?v1/(chat/completions|responses)$")
_OPENAI_EMBED_PATH = re.compile(r"^/?v1/embeddings$")
_OPENAI_TTS_PATH = re.compile(r"^/?v1/audio/speech$")
_ANTHROPIC_MESSAGES_PATH = re.compile(r"^/?v1/messages$")


def parse_usage(
    *,
    provider: str, # 'openai' | 'anthropic'
    path: str, # 'v1/chat/completions' 之類(不含 /openai 或 /anthropic 前綴)
    method: str,
    request_body: bytes,
    response_body: bytes,
    content_type: str,
    endpoint_full: str, # 完整 endpoint name 給 log(e.g. '/openai/v1/chat/completions')
) -> UsageEvent | None:
    """根據 path 分派。回 UsageEvent 或 None(未支援 endpoint)。

    永遠不 raise — parser 失敗回 None,caller log + 跳過。
    """
    try:
        return _dispatch(
            provider=provider,
            path=path,
            method=method,
            request_body=request_body,
            response_body=response_body,
            content_type=content_type,
            endpoint_full=endpoint_full,
        )
    except Exception as e: # noqa: BLE001
        _log.exception("usage_parser dispatch failed for %s: %s", endpoint_full, e)
        return None


def _dispatch(
    *,
    provider: str,
    path: str,
    method: str,
    request_body: bytes,
    response_body: bytes,
    content_type: str,
    endpoint_full: str,
) -> UsageEvent | None:
    if provider == "openai":
        if _OPENAI_CHAT_PATHS.match(path):
            model, usage = _parse_openai_chat_or_responses(
                request_body, response_body, content_type
            )
            if model is None or usage is None:
                return None
            cost = _compute_cost(
                provider, model,
                usage.get("input_tokens"), usage.get("output_tokens"),
                usage.get("cache_read_tokens"), None,
            )
            return UsageEvent(
                provider=provider, model=model, endpoint=endpoint_full,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cache_read_tokens=usage.get("cache_read_tokens"),
                cache_creation_tokens=None,
                cost_usd=cost,
            )
        if _OPENAI_EMBED_PATH.match(path):
            model, usage = _parse_openai_embeddings(request_body, response_body)
            if model is None or usage is None:
                return None
            cost = _compute_cost(provider, model, usage["input_tokens"], 0, 0, None)
            return UsageEvent(
                provider=provider, model=model, endpoint=endpoint_full,
                input_tokens=usage["input_tokens"],
                output_tokens=0, cache_read_tokens=0, cache_creation_tokens=None,
                cost_usd=cost,
            )
        if _OPENAI_TTS_PATH.match(path):
            model, char_count = _parse_openai_audio_speech(request_body)
            if model is None:
                return None
            from orion_model.tts_catalog import get_tts_pricing
            price_per_1m = get_tts_pricing("openai", model) or 0.0
            cost = round(char_count * price_per_1m / 1_000_000, 8)
            return UsageEvent(
                provider=provider, model=model, endpoint=endpoint_full,
                input_tokens=char_count, # 借 input_tokens 欄存 char count
                output_tokens=0, cache_read_tokens=0, cache_creation_tokens=None,
                cost_usd=cost,
            )
        # 未支援 openai endpoint → fallback log,cost=0
        return UsageEvent(
            provider=provider, model="unknown", endpoint=endpoint_full,
            input_tokens=None, output_tokens=None,
            cache_read_tokens=None, cache_creation_tokens=None,
            cost_usd=0.0,
        )

    if provider == "anthropic":
        if _ANTHROPIC_MESSAGES_PATH.match(path):
            model, usage = _parse_anthropic_messages(
                request_body, response_body, content_type
            )
            if model is None or usage is None:
                return None
            cost = _compute_cost(
                provider, model,
                usage.get("input_tokens"), usage.get("output_tokens"),
                usage.get("cache_read_tokens"), usage.get("cache_creation_tokens"),
            )
            return UsageEvent(
                provider=provider, model=model, endpoint=endpoint_full,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cache_read_tokens=usage.get("cache_read_tokens"),
                cache_creation_tokens=usage.get("cache_creation_tokens"),
                cost_usd=cost,
            )
        # 未支援 → fallback
        return UsageEvent(
            provider=provider, model="unknown", endpoint=endpoint_full,
            input_tokens=None, output_tokens=None,
            cache_read_tokens=None, cache_creation_tokens=None,
            cost_usd=0.0,
        )

    return None


__all__ = ["UsageEvent", "parse_usage"]
