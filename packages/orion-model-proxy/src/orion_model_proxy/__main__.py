"""orion-model-proxy entrypoint。

跑法:
    uv run --package orion-model-proxy orion-model-proxy
    # 或
    python -m orion_model_proxy

環境變數:
    ORION_MODEL_PROXY_HOST   listen host(default 127.0.0.1 — 改 0.0.0.0 對外)
    ORION_MODEL_PROXY_PORT   listen port(default 9090)
    ORION_MODEL_PROXY_KEY    Bearer token,沒設 = 不認證
    ANTHROPIC_API_KEY / OPENAI_API_KEY / OLLAMA_HOST  上游 provider keys
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

    print(
        f"[orion-model-proxy] listening on http://{host}:{port}"
        + ("(auth required)" if os.environ.get("ORION_MODEL_PROXY_KEY") else "(no auth)"),
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
