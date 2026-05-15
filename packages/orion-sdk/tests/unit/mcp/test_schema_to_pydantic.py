"""mcp/schema_to_pydantic.py — JSON Schema → Pydantic 動態建模。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orion_sdk.mcp.schema_to_pydantic import schema_to_pydantic_model


def test_simple_required_field() -> None:
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    model = schema_to_pydantic_model(schema)
    obj = model(path="/etc/hosts")
    assert obj.path == "/etc/hosts"  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        model()  # missing required


def test_optional_with_default() -> None:
    schema = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 100}},
    }
    model = schema_to_pydantic_model(schema)
    obj = model()
    assert obj.limit == 100  # type: ignore[attr-defined]


def test_optional_without_default_is_nullable() -> None:
    schema = {
        "type": "object",
        "properties": {"note": {"type": "string"}},
    }
    model = schema_to_pydantic_model(schema)
    obj = model()
    assert obj.note is None  # type: ignore[attr-defined]


def test_all_basic_types() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "score": {"type": "number"},
            "active": {"type": "boolean"},
        },
        "required": ["name"],
    }
    model = schema_to_pydantic_model(schema)
    obj = model(name="alice", age=30, score=98.5, active=True)
    assert obj.age == 30 and obj.score == 98.5 and obj.active is True  # type: ignore[attr-defined]


def test_array_of_strings() -> None:
    schema = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
    }
    model = schema_to_pydantic_model(schema)
    obj = model(tags=["a", "b"])
    assert obj.tags == ["a", "b"]  # type: ignore[attr-defined]


def test_nested_object_falls_back_to_dict() -> None:
    schema = {
        "type": "object",
        "properties": {"meta": {"type": "object", "properties": {"a": {"type": "string"}}}},
    }
    model = schema_to_pydantic_model(schema)
    obj = model(meta={"a": "x", "b": 5})  # 任意 dict 都接受
    assert obj.meta == {"a": "x", "b": 5}  # type: ignore[attr-defined]


def test_invalid_root_falls_back() -> None:
    """非 type=object 的 schema → fallback model(allow extra)。"""
    model = schema_to_pydantic_model({"type": "string"})
    obj = model(anything="goes")
    assert hasattr(obj, "model_dump")


def test_empty_properties_falls_back() -> None:
    model = schema_to_pydantic_model({"type": "object"})
    obj = model(arbitrary="field")
    assert hasattr(obj, "model_dump")


def test_nullable_type_list() -> None:
    """type 是 ["string", "null"] 列表時取第一個非 null。"""
    schema = {
        "type": "object",
        "properties": {"x": {"type": ["string", "null"]}},
    }
    model = schema_to_pydantic_model(schema)
    obj = model(x="hi")
    assert obj.x == "hi"  # type: ignore[attr-defined]


def test_extra_forbidden() -> None:
    """正常 ToolInput 模式應 forbid extra(避免 caller typo 過去)。"""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    model = schema_to_pydantic_model(schema)
    with pytest.raises(ValidationError):
        model(name="x", typo_field="y")
