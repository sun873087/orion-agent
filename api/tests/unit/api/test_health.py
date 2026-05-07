"""api/routes/health.py。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from orion_agent.api.app import create_app


def test_healthz() -> None:
    client = TestClient(create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
