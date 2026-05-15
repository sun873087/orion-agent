"""/healthz health check。

K8s readiness/liveness probe + production monitoring 用。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok"}
