"""orion-model-proxy entrypoint。

跑法:
    uv run --package orion-model-proxy orion-model-proxy
    # 或
    python -m orion_model_proxy

環境變數:
    ORION_MODEL_PROXY_HOST       listen host(default 127.0.0.1 — 改 0.0.0.0 對外)
    ORION_MODEL_PROXY_PORT       listen port(default 9090)
    ORION_MODEL_PROXY_ADMIN_KEY  admin Bearer(/admin REST + /admin/ui),沒設 admin 全 503
    ORION_PROXY_DB_URL           SQLAlchemy DSN(default SQLite at packages/orion-model-proxy/data/)
    ANTHROPIC_API_KEY / OPENAI_API_KEY / OLLAMA_HOST  上游 provider keys

User Bearer 由 admin 透過 /admin/ui 或 /admin/users/{id}/keys REST 為每位 user
個別產生(`sk-orion-<env>-<random>`),不再有單 token mode。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    # 只讀 per-app .env(packages/orion-model-proxy/.env);不抓 project root .env。
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")

    from orion_model_proxy.server import create_app

    # 把 proxy URL 自己 unset 進 process env — backend dispatch 不會繞回自己
    # (server._direct_provider 內已 bypass,但雙保險)
    os.environ.pop("ORION_MODEL_PROXY_URL", None)

    host = os.environ.get("ORION_MODEL_PROXY_HOST", "127.0.0.1")
    port = int(os.environ.get("ORION_MODEL_PROXY_PORT", "9090"))

    admin_set = bool(os.environ.get("ORION_MODEL_PROXY_ADMIN_KEY"))
    print(
        f"[orion-model-proxy] listening on http://{host}:{port}"
        + ("  (admin endpoints: enabled)" if admin_set else "  (admin endpoints: 503 — set ORION_MODEL_PROXY_ADMIN_KEY)"),
        file=sys.stderr,
        flush=True,
    )
    uvicorn.run(
        create_app(),
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
