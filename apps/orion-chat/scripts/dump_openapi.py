"""Dump FastAPI openapi.json → apps/orion-chat/shared/openapi.json。

跑法:
  npm run gen:openapi
  (= uv run --package orion-chat-api python apps/orion-chat/scripts/dump_openapi.py)
"""

from __future__ import annotations

import json
from pathlib import Path

from orion_chat_api.app import app

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT = REPO_ROOT / "apps/orion-chat/shared/openapi.json"


def main() -> None:
    schema = app.openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
