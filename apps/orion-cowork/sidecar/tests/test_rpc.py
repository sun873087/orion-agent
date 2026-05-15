"""RPC server smoke tests — handler dispatch + error handling。

跑法:子進程拉 sidecar 起來,塞 stdin,讀 stdout。比 mock sys.stdin/stdout 穩。
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest


def _run_sidecar(stdin_text: str, *, extra_module: str | None = None, timeout: float = 5.0) -> list[dict]:
    """跑一個臨時 sidecar,送 stdin,等 EOF/結束,回 parsed frames。

    extra_module:若傳,先 exec 它(自訂 handlers 覆蓋 Handlers().methods())。
    """
    if extra_module:
        cmd = [sys.executable, "-c", extra_module]
    else:
        cmd = [sys.executable, "-m", "orion_cowork_sidecar"]
    proc = subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = proc.stdout.strip()
    return [json.loads(line) for line in out.split("\n") if line]


def test_ping() -> None:
    frames = _run_sidecar('{"id":"1","method":"ping"}\n')
    assert frames[0] == {"event": "sidecar.ready"}
    assert frames[1] == {"id": "1", "event": "pong", "final": True}
    assert not any(f.get("event") == "done" for f in frames[2:])


def test_unknown_method() -> None:
    frames = _run_sidecar('{"id":"42","method":"bogus"}\n')
    err = next(f for f in frames if f.get("id") == "42")
    assert err["error"]["code"] == "METHOD_NOT_FOUND"
    assert err["final"] is True


def test_malformed_json_skipped() -> None:
    frames = _run_sidecar('not json\n{"id":"1","method":"ping"}\n')
    # ready + warn log + pong (順序固定)
    assert frames[0] == {"event": "sidecar.ready"}
    assert any(f.get("event") == "log" and f.get("level") == "warn" for f in frames)
    assert any(f.get("id") == "1" and f.get("event") == "pong" for f in frames)


@pytest.mark.parametrize("count", [1, 3, 10])
def test_echo_multiple_requests(count: int) -> None:
    # 自訂 handlers 加 echo,demo 並行 dispatch
    custom = textwrap.dedent('''
        import asyncio
        from orion_cowork_sidecar.rpc import RpcServer
        async def echo(params):
            yield {"event": "echo", "data": params, "final": True}
        async def _main():
            await RpcServer({"echo": echo}).serve()
        asyncio.run(_main())
    ''')
    payload = "".join(
        f'{{"id":"{i}","method":"echo","params":{{"n":{i}}}}}\n'
        for i in range(count)
    )
    frames = _run_sidecar(payload, extra_module=custom)
    echo_frames = [f for f in frames if f.get("event") == "echo"]
    assert len(echo_frames) == count
    assert {f["id"] for f in echo_frames} == {str(i) for i in range(count)}


def test_handler_exception_wrapped() -> None:
    custom = textwrap.dedent('''
        import asyncio
        from orion_cowork_sidecar.rpc import RpcServer
        async def boom(_params):
            raise ValueError("kaboom")
            yield {}
        async def _main():
            await RpcServer({"boom": boom}).serve()
        asyncio.run(_main())
    ''')
    frames = _run_sidecar('{"id":"7","method":"boom"}\n', extra_module=custom)
    err = next(f for f in frames if f.get("id") == "7")
    assert err["error"]["code"] == "VALUEERROR"
    assert "kaboom" in err["error"]["message"]
    assert err["final"] is True
