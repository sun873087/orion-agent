"""JSON Schema → Pydantic v2 動態建模。

對應 spec § 5 schema_to_pydantic.py。

只支援 MCP tools 常見的扁平 type=object schema:
- properties:string / integer / number / boolean
- properties:array of string(其他 array 退化成 list[str])
- properties:nested object(退化成 dict[str, Any])

不支援(失敗 fallback 給 dict[str, Any]):
- $ref / definitions
- anyOf / oneOf / allOf
- 深層 nested

對應 ToolInput pattern:新建的 model 繼承 ToolInput
(`model_config = {"extra": "forbid"}`)。

Args:
    schema: 來自 MCP server 的 inputSchema dict
    model_name: 給動態 model 的 class name(供 debug / pydantic err msg)

Returns:
    type[ToolInput] subclass
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, create_model

from orion_sdk.core.tool import ToolInput

_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def _resolve_field_type(prop_schema: dict[str, Any]) -> Any:
    """解析單一 property 的 Python 型別。"""
    t = prop_schema.get("type")

    if isinstance(t, list):
        # ["string", "null"] 之類 → 取第一個非 null
        non_null = [x for x in t if x != "null"]
        t = non_null[0] if non_null else "string"

    if t in _TYPE_MAP:
        return _TYPE_MAP[t]

    if t == "array":
        items = prop_schema.get("items", {})
        if isinstance(items, dict) and items.get("type") == "string":
            return list[str]
        return list[Any]

    if t == "object":
        # nested object 退化成 dict
        return dict[str, Any]

    # 其他(沒寫 type / enum-only / 未知)→ Any
    return Any


def schema_to_pydantic_model(
    schema: dict[str, Any],
    *,
    model_name: str = "DynamicMcpInput",
) -> type[ToolInput]:
    """動態建一個 ToolInput subclass。

    schema 不合法(非 type=object / 無 properties)→ 回 fallback model
    (任意 dict 都接受)。
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return _fallback_model(model_name)

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return _fallback_model(model_name)

    required = set(schema.get("required", []) or [])

    fields: dict[str, Any] = {}
    for name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue

        field_type: Any
        try:
            field_type = _resolve_field_type(prop_schema)
        except Exception: # noqa: BLE001
            field_type = Any

        description = prop_schema.get("description")

        if name in required:
            default: Any = ...
        elif "default" in prop_schema:
            default = prop_schema["default"]
        else:
            # 非 required + 無 default → Optional with None
            field_type = field_type | None
            default = None

        # Pydantic create_model 的 (type, FieldInfo) 格式
        fields[name] = (
            field_type,
            Field(default=default, description=description),
        )

    if not fields:
        return _fallback_model(model_name)

    # create_model 動態建 ToolInput subclass
    model: type[ToolInput] = create_model(
        model_name,
        __base__=ToolInput,
        **fields,
    )
    return model


def _fallback_model(model_name: str) -> type[ToolInput]:
    """fallback:接任意 dict 作 input。"""

    class _FallbackInput(ToolInput):
        # 允許任意欄位
        model_config = {"extra": "allow"}

    _FallbackInput.__name__ = model_name
    return _FallbackInput
