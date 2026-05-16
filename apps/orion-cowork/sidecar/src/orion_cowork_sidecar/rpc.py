"""Stdio JSON-RPC loop。

Wire format(newline-delimited JSON):

Request   {"id": "...", "method": "...", "params": {...}}
Response  {"id": "...", "event": "...", "data": {...}}            (streaming, 多筆)
          {"id": "...", "event": "...", "final": true}             (最後一筆)
Error     {"id": "...", "error": {"code": "...", "message": "..."}, "final": true}
Notify    {"event": "...", ...}                                    (sidecar→main 主動)

每個 request 由獨立 asyncio task 處理(允許 in-flight concurrency)。stdin EOF
觸發 graceful shutdown — outstanding tasks 收到 cancel。
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from collections.abc import AsyncIterator, Callable
from typing import Any

# Handler signature: async generator yielding dict frames (without `id`)。
# RPC layer 自動 attach id 跟 final flag。
HandlerFn = Callable[[dict[str, Any]], AsyncIterator[dict[str, Any]]]


class RpcServer:
    def __init__(self, handlers: dict[str, HandlerFn]) -> None:
        self._handlers = handlers
        self._tasks: set[asyncio.Task[None]] = set()
        self._write_lock = asyncio.Lock()

    async def _write_frame(self, frame: dict[str, Any]) -> None:
        async with self._write_lock:
            sys.stdout.write(json.dumps(frame, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    async def _dispatch(self, req: dict[str, Any]) -> None:
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        handler = self._handlers.get(method or "")
        if handler is None:
            await self._write_frame({
                "id": rid,
                "error": {"code": "METHOD_NOT_FOUND", "message": f"unknown method: {method!r}"},
                "final": True,
            })
            return
        saw_final = False
        try:
            async for frame in handler(params):
                if frame.get("final"):
                    saw_final = True
                out = {"id": rid, **frame}
                await self._write_frame(out)
            if not saw_final:
                await self._write_frame({"id": rid, "event": "done", "final": True})
        except asyncio.CancelledError:
            await self._write_frame({
                "id": rid,
                "error": {"code": "CANCELLED", "message": "request cancelled"},
                "final": True,
            })
            raise
        except Exception as e:  # noqa: BLE001
            await self._write_frame({
                "id": rid,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e),
                    "trace": traceback.format_exc(),
                },
                "final": True,
            })

    async def serve(self) -> None:
        await self._write_frame({"event": "sidecar.ready"})

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await reader.readline()
            except Exception as e:  # noqa: BLE001
                await self._write_frame({
                    "event": "log",
                    "level": "error",
                    "message": f"stdin read error: {e}",
                })
                break
            if not line:  # EOF — main process closed stdin
                break
            try:
                req = json.loads(line.decode("utf-8").strip())
            except json.JSONDecodeError as e:
                await self._write_frame({
                    "event": "log",
                    "level": "warn",
                    "message": f"malformed JSON ignored: {e}",
                })
                continue
            task = asyncio.create_task(self._dispatch(req))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        # Graceful shutdown:先等 in-flight tasks 完成(最多 5 秒),才強制 cancel。
        # 避免 stdin EOF 立刻打斷 DB write 等不可中斷的工作。
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                for t in list(self._tasks):
                    t.cancel()
                await asyncio.gather(*self._tasks, return_exceptions=True)
