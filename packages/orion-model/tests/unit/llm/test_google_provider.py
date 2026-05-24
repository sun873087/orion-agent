"""Google Gemini provider(native API)— smoke / cost / translation tests。"""

from __future__ import annotations

import json

import httpx
import pytest

from orion_model.errors import ProviderHTTPError
from orion_model.google_provider import (
    GoogleProvider,
    _clean_schema_for_gemini,
    _map_finish_reason,
    _translate_messages_to_gemini,
    _translate_tools_to_gemini,
)
from orion_model.tool_def import ToolDefinition
from orion_model.types import (
    ImageBlock,
    NormalizedMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


# ─── Provider basics ────────────────────────────────────────────


def test_provider_name() -> None:
    assert GoogleProvider.name == "google"


def test_provider_instantiation_uses_static_catalog() -> None:
    p = GoogleProvider(model="gemini-3.5-flash")
    assert p.model == "gemini-3.5-flash"
    assert p.capabilities.max_context_tokens == 1_000_000
    assert p.capabilities.parallel_tool_calls is True


def test_provider_unknown_model_default_context() -> None:
    p = GoogleProvider(model="gemini-99-unknown")
    assert p.capabilities.max_context_tokens == 1_000_000


def test_cost_gemini_3_5_flash() -> None:
    p = GoogleProvider(model="gemini-3.5-flash")
    # 1M in + 1M out = 0.30 + 2.50 = 2.80 USD
    cost = p.estimate_cost(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(2.80)


def test_cost_unknown_model_zero() -> None:
    p = GoogleProvider(model="gemini-ghost")
    cost = p.estimate_cost(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 0.0


# ─── _map_finish_reason ─────────────────────────────────────────


def test_finish_reason_map() -> None:
    assert _map_finish_reason("STOP") == "end_turn"
    assert _map_finish_reason(None) == "end_turn"
    assert _map_finish_reason("MAX_TOKENS") == "max_tokens"
    assert _map_finish_reason("SAFETY") == "content_filter"
    assert _map_finish_reason("RECITATION") == "content_filter"
    assert _map_finish_reason("WEIRD") == "end_turn"


# ─── Translation:tools ─────────────────────────────────────────


def test_translate_tools_to_gemini_packs_into_functionDeclarations() -> None:
    """Gemini 把所有 functions 包成單一 tool 物件的 functionDeclarations list。"""
    tools = [
        ToolDefinition(
            name="Bash",
            description="Run shell",
            input_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
        ),
        ToolDefinition(
            name="Read",
            description="Read file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    ]
    out = _translate_tools_to_gemini(tools)
    assert len(out) == 1
    assert "functionDeclarations" in out[0]
    decls = out[0]["functionDeclarations"]
    assert len(decls) == 2
    assert decls[0]["name"] == "Bash"
    assert decls[1]["name"] == "Read"


def test_clean_schema_drops_unsupported_keys() -> None:
    """Pydantic schema 帶的 $schema / title / additionalProperties — Gemini 嫌,
    全部砍掉。"""
    schema = {
        "$schema": "http://json-schema.org",
        "title": "BashInput",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cmd": {"type": "string", "title": "Command"},
        },
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert "$schema" not in cleaned
    assert "title" not in cleaned
    assert "additionalProperties" not in cleaned
    assert cleaned["properties"]["cmd"] == {"type": "string"}


def test_clean_schema_drops_exclusive_min_max() -> None:
    """Pydantic 2 用 draft 2020-12 — `exclusiveMinimum: 0` 是 number,
    Gemini 期 OpenAPI 3.0 (boolean) → 砍掉。"""
    schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "exclusiveMinimum": 0, "exclusiveMaximum": 100},
        },
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert "exclusiveMinimum" not in cleaned["properties"]["limit"]
    assert "exclusiveMaximum" not in cleaned["properties"]["limit"]
    assert cleaned["properties"]["limit"] == {"type": "integer"}


def test_clean_schema_inlines_defs_refs() -> None:
    """Pydantic 對 nested model 產 $defs + $ref — Gemini 沒 ref resolution,
    必須 inline 展開。"""
    schema = {
        "type": "object",
        "$defs": {
            "Item": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        },
        "properties": {
            "items": {
                "type": "array",
                "items": {"$ref": "#/$defs/Item"},
            },
        },
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert "$defs" not in cleaned
    # items.items 應該被 inline 成 Item 的展開
    assert cleaned["properties"]["items"]["items"] == {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }


def test_clean_schema_inlines_nested_refs() -> None:
    """$ref 指到的 target 內也可能再有 $ref → 連環 inline 都要解掉。"""
    schema = {
        "$defs": {
            "Outer": {
                "type": "object",
                "properties": {"inner": {"$ref": "#/$defs/Inner"}},
            },
            "Inner": {"type": "string"},
        },
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/Outer"}},
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert cleaned["properties"]["x"] == {
        "type": "object",
        "properties": {"inner": {"type": "string"}},
    }


def test_clean_schema_legacy_definitions_alias() -> None:
    """OpenAPI / Pydantic v1 風格用 `definitions` 而非 `$defs` — 同樣支援。"""
    schema = {
        "definitions": {
            "Foo": {"type": "integer"},
        },
        "properties": {"v": {"$ref": "#/definitions/Foo"}},
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert "definitions" not in cleaned
    assert cleaned["properties"]["v"] == {"type": "integer"}


def test_clean_schema_unknown_ref_falls_back_empty() -> None:
    """$ref 指到不存在的 target → 空 dict(Gemini 視為 any)。"""
    schema = {"properties": {"x": {"$ref": "#/$defs/Ghost"}}}
    cleaned = _clean_schema_for_gemini(schema)
    assert cleaned["properties"]["x"] == {}


def test_clean_schema_filters_empty_enum_values() -> None:
    """Gemini 拒 enum 內空字串 — Pydantic 對 Literal["a", "b", "c", ""]
    會吐空字串。filter 掉但留其他值。"""
    schema = {
        "properties": {
            "state": {
                "type": "string",
                "enum": ["pending", "active", "done", ""],
            },
        },
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert cleaned["properties"]["state"]["enum"] == ["pending", "active", "done"]


def test_clean_schema_empty_enum_list_drops_key() -> None:
    """enum 全是空字串/None → 砍整個 enum key(讓 Gemini 視為 free string)。"""
    schema = {
        "properties": {
            "x": {"type": "string", "enum": ["", None, ""]},
        },
    }
    cleaned = _clean_schema_for_gemini(schema)
    assert "enum" not in cleaned["properties"]["x"]
    assert cleaned["properties"]["x"] == {"type": "string"}


def test_clean_schema_preserves_integer_zero_in_enum() -> None:
    """integer enum 內的 0 不能被當 'empty' 砍掉 — falsy != empty。"""
    schema = {"properties": {"n": {"type": "integer", "enum": [0, 1, 2]}}}
    cleaned = _clean_schema_for_gemini(schema)
    assert cleaned["properties"]["n"]["enum"] == [0, 1, 2]


# ─── Translation:messages ──────────────────────────────────────


def test_translate_simple_text() -> None:
    msgs = [
        NormalizedMessage(role="user", content="hi"),
        NormalizedMessage(role="assistant", content="hello"),
    ]
    out = _translate_messages_to_gemini(msgs)
    assert out == [
        {"role": "user", "parts": [{"text": "hi"}]},
        {"role": "model", "parts": [{"text": "hello"}]},
    ]


def test_translate_image_uses_inlineData() -> None:
    msg = NormalizedMessage(
        role="user",
        content=[
            TextBlock(text="see this"),
            ImageBlock(media_type="image/png", data="BASE64DATA"),
        ],
    )
    out = _translate_messages_to_gemini([msg])
    parts = out[0]["parts"]
    assert parts[0] == {"text": "see this"}
    assert parts[1] == {
        "inlineData": {"mimeType": "image/png", "data": "BASE64DATA"},
    }


def test_translate_tool_use_preserves_signature() -> None:
    """Assistant ToolUseBlock 帶 thought_signature → parts 內 functionCall +
    thoughtSignature 同 part。multi-turn 跨 tool call 不會被 Gemini 400。"""
    msg = NormalizedMessage(
        role="assistant",
        content=[
            TextBlock(text="let me run"),
            ToolUseBlock(
                id="tu_1", name="Bash", input={"cmd": "ls"},
                thought_signature="SIG_ABC",
            ),
        ],
    )
    out = _translate_messages_to_gemini([msg])
    parts = out[0]["parts"]
    assert parts[0] == {"text": "let me run"}
    assert parts[1] == {
        "functionCall": {"name": "Bash", "args": {"cmd": "ls"}},
        "thoughtSignature": "SIG_ABC",
    }


def test_translate_tool_use_signature_in_input_legacy() -> None:
    """Backward-compat:thought_signature 也可從 input 內 __thought_signature__ 拿
    (stream() 回傳 full_input 把 signature 塞進 input dict)。"""
    msg = NormalizedMessage(
        role="assistant",
        content=[
            ToolUseBlock(
                id="tu_1", name="Bash",
                input={"cmd": "ls", "__thought_signature__": "SIG_FROM_INPUT"},
            ),
        ],
    )
    out = _translate_messages_to_gemini([msg])
    fc = out[0]["parts"][0]
    assert fc["functionCall"]["args"] == {"cmd": "ls"} # __thought_signature__ 被 strip
    assert fc["thoughtSignature"] == "SIG_FROM_INPUT"


def test_translate_tool_result_resolves_function_name() -> None:
    """user ToolResultBlock → role=user functionResponse,name 從 tool_use_id
    反查回 ToolUseBlock.name。"""
    msgs = [
        NormalizedMessage(
            role="assistant",
            content=[
                ToolUseBlock(id="tu_1", name="Bash", input={"cmd": "ls"}),
            ],
        ),
        NormalizedMessage(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="tu_1", content="file.txt"),
            ],
        ),
    ]
    out = _translate_messages_to_gemini(msgs)
    # 第二條應是 functionResponse with name=Bash
    assert out[1]["role"] == "user"
    fr = out[1]["parts"][0]["functionResponse"]
    assert fr["name"] == "Bash"
    assert fr["response"] == {"output": "file.txt"}


def test_translate_tool_result_unknown_id_falls_back_unknown() -> None:
    """ToolResultBlock 對應不到 ToolUseBlock(罕見) → name='unknown' fallback。"""
    msg = NormalizedMessage(
        role="user",
        content=[ToolResultBlock(tool_use_id="ghost", content="x")],
    )
    out = _translate_messages_to_gemini([msg])
    fr = out[0]["parts"][0]["functionResponse"]
    assert fr["name"] == "unknown"


def test_translate_empty_messages_empty_output() -> None:
    assert _translate_messages_to_gemini([]) == []


# ─── stream():HTTP 4xx/5xx → ProviderHTTPError(不再裸 httpx) ─────


def _make_mock_client(status_code: int, body: dict | str) -> httpx.AsyncClient:
    """建一個 httpx.AsyncClient 用 MockTransport,所有 request 都回固定 response。"""
    body_bytes = (
        json.dumps(body).encode("utf-8") if isinstance(body, dict)
        else body.encode("utf-8")
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body_bytes)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_stream_429_raises_friendly_provider_error() -> None:
    """Gemini 429(quota)→ raise ProviderHTTPError 帶中文 quota 訊息 +
    status_code=429,sidecar `_format_send_error` 能識別套 RATE_LIMIT。"""
    body = {"error": {"code": 429, "message": "Quota exceeded for free tier"}}
    client = _make_mock_client(429, body)
    p = GoogleProvider(model="gemini-3.5-flash", client=client)

    with pytest.raises(ProviderHTTPError) as exc_info:
        async for _ in p.stream(system="", messages=[NormalizedMessage(role="user", content="hi")]):
            pass

    assert exc_info.value.status_code == 429
    assert exc_info.value.provider == "google"
    assert "Quota exceeded" in exc_info.value.upstream_message
    assert "Gemini" in str(exc_info.value)


@pytest.mark.asyncio
async def test_stream_400_includes_upstream_validation_msg() -> None:
    """Gemini 400 (schema invalid) — message 帶 upstream 細節讓 user 看清楚錯哪。"""
    body = {"error": {"code": 400, "message": "Unknown field 'exclusiveMinimum'"}}
    client = _make_mock_client(400, body)
    p = GoogleProvider(model="gemini-3.5-flash", client=client)

    with pytest.raises(ProviderHTTPError) as exc_info:
        async for _ in p.stream(system="", messages=[NormalizedMessage(role="user", content="hi")]):
            pass

    assert exc_info.value.status_code == 400
    assert "exclusiveMinimum" in str(exc_info.value)


@pytest.mark.asyncio
async def test_stream_500_with_non_json_body_still_raises_cleanly() -> None:
    """Gemini 5xx 有時 body 不是 JSON(HTML error page)— parse 失敗別爆。"""
    client = _make_mock_client(503, "<html>Service Unavailable</html>")
    p = GoogleProvider(model="gemini-3.5-flash", client=client)

    with pytest.raises(ProviderHTTPError) as exc_info:
        async for _ in p.stream(system="", messages=[NormalizedMessage(role="user", content="hi")]):
            pass

    assert exc_info.value.status_code == 503
    assert exc_info.value.upstream_message == "" # parse 失敗 → 空字串
    assert "503" in str(exc_info.value)
