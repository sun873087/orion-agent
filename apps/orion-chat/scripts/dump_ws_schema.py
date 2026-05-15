"""Dump WebSocket event 的 pydantic JSON schema → shared/ws-events.schema.json。

跑法:
  npm run gen:ws-schema
  (= uv run --package orion-chat-api python apps/orion-chat/scripts/dump_ws_schema.py)

ClientEvent / ServerEvent 是 discriminated union。`TypeAdapter.json_schema()` 把
union 整體攤平成 JSON Schema(包括 $defs),適合 json-schema-to-typescript 吃。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from orion_chat_api.event_schema import ClientEvent, ServerEvent

REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED = REPO_ROOT / "apps/orion-chat/shared"

# 拆兩個檔(各自完整 $defs),避免 json-schema-to-typescript 跨 $defs 解析錯。
TARGETS = [
    ("ws-client-events.schema.json", "Orion Chat Client→Server Events", ClientEvent),
    ("ws-server-events.schema.json", "Orion Chat Server→Client Events", ServerEvent),
]


def main() -> None:
    SHARED.mkdir(parents=True, exist_ok=True)
    for filename, title, adapter_type in TARGETS:
        schema = TypeAdapter(adapter_type).json_schema()
        schema["$schema"] = "http://json-schema.org/draft-07/schema#"
        schema["title"] = title
        (SHARED / filename).write_text(
            json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        )
        print(f"wrote apps/orion-chat/shared/{filename}")


if __name__ == "__main__":
    main()
