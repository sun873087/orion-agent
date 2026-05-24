"""usage_parser per-endpoint。"""

from __future__ import annotations

import json

import pytest

from orion_model_proxy.usage_parser import parse_usage


# ─── OpenAI chat completions ─────────────────────────────────────────────


def test_openai_chat_non_stream() -> None:
    req = json.dumps({"model": "gpt-5-mini", "messages": [{"role": "user", "content": "hi"}]}).encode()
    resp = json.dumps({
        "id": "chatcmpl-1",
        "model": "gpt-5-mini",
        "choices": [{"message": {"role": "assistant", "content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }).encode()
    ev = parse_usage(
        provider="openai", path="v1/chat/completions", method="POST",
        request_body=req, response_body=resp, content_type="application/json",
        endpoint_full="/openai/v1/chat/completions",
    )
    assert ev is not None
    assert ev.model == "gpt-5-mini"
    assert ev.input_tokens == 10
    assert ev.output_tokens == 5
    # gpt-5-mini pricing: input 0.25 / output 1.0 per 1M
    expected = 10 * 0.25 / 1_000_000 + 5 * 1.0 / 1_000_000
    assert abs(ev.cost_usd - expected) < 1e-10


def test_openai_chat_with_cached_tokens() -> None:
    req = json.dumps({"model": "gpt-5"}).encode()
    resp = json.dumps({
        "model": "gpt-5",
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 800},
        },
    }).encode()
    ev = parse_usage(
        provider="openai", path="v1/chat/completions", method="POST",
        request_body=req, response_body=resp, content_type="application/json",
        endpoint_full="/openai/v1/chat/completions",
    )
    assert ev is not None
    assert ev.cache_read_tokens == 800
    # fresh input = 1000 - 800 = 200
    # gpt-5: input 2.5 / output 10 / cache_read 0.625 per 1M
    expected = 200 * 2.5 / 1e6 + 100 * 10 / 1e6 + 800 * 0.625 / 1e6
    assert abs(ev.cost_usd - expected) < 1e-10


def test_openai_chat_stream_with_usage() -> None:
    """Stream 模式 — client 要設 stream_options.include_usage=true 才會有最後 usage chunk。"""
    sse = (
        b'data: {"id":"x","model":"gpt-5-mini","choices":[{"delta":{"content":"hi"}}]}\n\n'
        b'data: {"id":"x","model":"gpt-5-mini","choices":[],"usage":{"prompt_tokens":12,"completion_tokens":8}}\n\n'
        b"data: [DONE]\n\n"
    )
    req = json.dumps({"model": "gpt-5-mini", "stream": True}).encode()
    ev = parse_usage(
        provider="openai", path="v1/chat/completions", method="POST",
        request_body=req, response_body=sse, content_type="text/event-stream",
        endpoint_full="/openai/v1/chat/completions",
    )
    assert ev is not None
    assert ev.model == "gpt-5-mini"
    assert ev.input_tokens == 12
    assert ev.output_tokens == 8


def test_openai_chat_stream_no_usage_returns_none() -> None:
    """沒 include_usage 的 stream → 抓不到 token,parser 回 None。"""
    sse = (
        b'data: {"model":"gpt-5","choices":[{"delta":{"content":"a"}}]}\n\n'
        b'data: [DONE]\n\n'
    )
    req = json.dumps({"model": "gpt-5", "stream": True}).encode()
    ev = parse_usage(
        provider="openai", path="v1/chat/completions", method="POST",
        request_body=req, response_body=sse, content_type="text/event-stream",
        endpoint_full="/openai/v1/chat/completions",
    )
    assert ev is None


# ─── OpenAI Responses API ────────────────────────────────────────────────


def test_openai_responses_non_stream() -> None:
    """Responses API 用 input_tokens / output_tokens 命名(跟 chat completions 不同)。"""
    req = json.dumps({"model": "gpt-5", "input": "hi"}).encode()
    resp = json.dumps({
        "model": "gpt-5",
        "usage": {"input_tokens": 20, "output_tokens": 30},
    }).encode()
    ev = parse_usage(
        provider="openai", path="v1/responses", method="POST",
        request_body=req, response_body=resp, content_type="application/json",
        endpoint_full="/openai/v1/responses",
    )
    assert ev is not None
    assert ev.input_tokens == 20
    assert ev.output_tokens == 30


# ─── Embeddings ──────────────────────────────────────────────────────────


def test_openai_embeddings() -> None:
    req = json.dumps({"model": "text-embedding-3-small", "input": "hi"}).encode()
    resp = json.dumps({
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }).encode()
    ev = parse_usage(
        provider="openai", path="v1/embeddings", method="POST",
        request_body=req, response_body=resp, content_type="application/json",
        endpoint_full="/openai/v1/embeddings",
    )
    assert ev is not None
    assert ev.input_tokens == 5
    # text-embedding-3-small 不在 chat catalog,pricing None → cost=0
    assert ev.cost_usd == 0.0


# ─── Audio TTS ───────────────────────────────────────────────────────────


def test_openai_audio_speech() -> None:
    """input 字元數 × tts pricing。"""
    text = "Hello world, this is a test of TTS." # 35 chars
    req = json.dumps({"model": "gpt-4o-mini-tts", "input": text, "voice": "alloy"}).encode()
    ev = parse_usage(
        provider="openai", path="v1/audio/speech", method="POST",
        request_body=req, response_body=b"\xff\xfb\x90\x44", # 假 mp3 bytes
        content_type="audio/mpeg",
        endpoint_full="/openai/v1/audio/speech",
    )
    assert ev is not None
    assert ev.model == "gpt-4o-mini-tts"
    assert ev.input_tokens == len(text)
    # gpt-4o-mini-tts pricing 從 tts catalog 查,沒設則 cost=0
    assert ev.cost_usd >= 0


# ─── Anthropic messages ──────────────────────────────────────────────────


def test_anthropic_messages_non_stream() -> None:
    req = json.dumps({
        "model": "claude-haiku-4-5", "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()
    resp = json.dumps({
        "id": "msg_1", "model": "claude-haiku-4-5",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hi!"}],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 0,
        },
    }).encode()
    ev = parse_usage(
        provider="anthropic", path="v1/messages", method="POST",
        request_body=req, response_body=resp, content_type="application/json",
        endpoint_full="/anthropic/v1/messages",
    )
    assert ev is not None
    assert ev.model == "claude-haiku-4-5"
    assert ev.input_tokens == 100
    assert ev.output_tokens == 50
    assert ev.cache_read_tokens == 80


def test_anthropic_messages_stream() -> None:
    """SSE 解 message_start + message_delta 累加 — output_tokens 取最後一筆 delta 的值。"""
    sse = (
        b'event: message_start\n'
        b'data: {"type":"message_start","message":{"id":"x","model":"claude-haiku-4-5",'
        b'"usage":{"input_tokens":50,"output_tokens":1}}}\n\n'
        b'event: content_block_delta\n'
        b'data: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n'
        b'event: message_delta\n'
        b'data: {"type":"message_delta","delta":{},"usage":{"output_tokens":15}}\n\n'
        b'event: message_stop\n'
        b'data: {"type":"message_stop"}\n\n'
    )
    req = json.dumps({"model": "claude-haiku-4-5", "stream": True}).encode()
    ev = parse_usage(
        provider="anthropic", path="v1/messages", method="POST",
        request_body=req, response_body=sse, content_type="text/event-stream",
        endpoint_full="/anthropic/v1/messages",
    )
    assert ev is not None
    assert ev.input_tokens == 50
    assert ev.output_tokens == 15 # 最後 delta 的值


# ─── Fallback / edge cases ───────────────────────────────────────────────


def test_unknown_openai_endpoint_returns_fallback() -> None:
    """未支援 endpoint 回 fallback event(cost=0,model=unknown)讓 admin 看得到 hit。"""
    ev = parse_usage(
        provider="openai", path="v1/files", method="POST",
        request_body=b"", response_body=b"{}", content_type="application/json",
        endpoint_full="/openai/v1/files",
    )
    assert ev is not None
    assert ev.model == "unknown"
    assert ev.cost_usd == 0.0


def test_invalid_json_response_returns_none() -> None:
    """Response 不是合法 JSON → 不該 crash,回 None。"""
    ev = parse_usage(
        provider="openai", path="v1/chat/completions", method="POST",
        request_body=json.dumps({"model": "gpt-5"}).encode(),
        response_body=b"not json",
        content_type="application/json",
        endpoint_full="/openai/v1/chat/completions",
    )
    assert ev is None


def test_unknown_provider_returns_none() -> None:
    # google 已 supported,改用真未知 provider 測 dispatch fallback
    ev = parse_usage(
        provider="cohere", path="v1/anything", method="POST",
        request_body=b"", response_body=b"{}", content_type="application/json",
        endpoint_full="/cohere/v1/anything",
    )
    assert ev is None
