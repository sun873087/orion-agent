"""orion-chat-api entrypoint(取代原 `orion serve`)。

跑法:
  orion-chat-api serve --host 0.0.0.0 --port 8000
  orion-chat-api serve --db-url postgresql+asyncpg://...
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from dotenv import load_dotenv

# 只讀 per-app .env(apps/orion-chat/.env);不抓 project root .env。
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

os.environ.setdefault("ORION_CLIENT_ID", "orion-chat-api")

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Listen port.")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Dev reload.")] = False,
    db_url: Annotated[
        str | None,
        typer.Option(
            "--db-url",
            help=(
                "Database URL,等同 ORION_DB_URL。如 postgresql+asyncpg://... 或 "
                "sqlite+aiosqlite:///./orion.db。未設 → in-memory SessionManager。"
            ),
        ),
    ] = None,
) -> None:
    """啟動 FastAPI server(uvicorn)。"""
    if db_url:
        os.environ["ORION_DB_URL"] = db_url

    uvicorn.run(
        "orion_chat_api.app:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["src"] if reload else None,
        log_level="info",
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
