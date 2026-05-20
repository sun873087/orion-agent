"""FastAPI 層。

把 CLI agent(-5)包成 web backend:HTTP/WebSocket endpoints。

入口:`orion serve --port 8000`(Step 9 的 main.py subcommand)。

範圍:
- WebSocket /chat/stream/{session_id}(雙向串流 + permission ask round-trip)
- REST /sessions(POST/GET/DELETE)
- /auth/login(JWT dev mode)
- /healthz

換 Postgres / Redis / 真 OAuth / multi-instance。
"""

from orion_chat_api.app import create_app

__all__ = ["create_app"]
