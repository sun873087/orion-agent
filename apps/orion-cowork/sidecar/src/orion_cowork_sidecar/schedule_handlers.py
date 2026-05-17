"""Schedule RPC handlers — CRUD + run_now。

模組式 bind:`bind_schedule_handlers(handlers)` 回 dict[method_name → handler]
讓 Handlers.methods() 一行展開,不必每個 RPC 都寫 self method。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from orion_cowork_sidecar import storage
from orion_cowork_sidecar.scheduler import compute_next_run_at, is_valid_cron

if TYPE_CHECKING:
    from orion_cowork_sidecar.handlers import Handlers


def _schedule_to_dict(s: storage.Schedule) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "cron_expr": s.cron_expr,
        "trigger_type": s.trigger_type,
        "payload": s.payload,
        "scope": "project" if s.project_id else "user",
        "project_id": s.project_id,
        "enabled": s.enabled,
        "last_run_at": s.last_run_at,
        "next_run_at": s.next_run_at,
        "last_run_session_id": s.last_run_session_id,
        "last_run_status": s.last_run_status,
        "last_error": s.last_error,
        "model_provider": s.model_provider,
        "model": s.model,
        "workspace_dir": s.workspace_dir,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "target_session_id": s.target_session_id,
        "kind": "loop" if s.target_session_id else "schedule",
    }


def bind_schedule_handlers(handlers: "Handlers") -> dict[str, Any]:
    """Build closure handlers bound to a specific Handlers instance。"""

    async def schedule_list(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        engine = await handlers.ensure_engine()
        scope_raw = params.get("scope")
        scope = scope_raw if scope_raw in ("user", "project", "all") else "all"
        project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
        items = await storage.list_schedules(
            engine, scope=scope, project_id=project_id,
        )
        yield {
            "event": "schedule_list",
            "data": {"schedules": [_schedule_to_dict(s) for s in items]},
            "final": True,
        }

    async def schedule_get(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("id")
        if not isinstance(sid, str) or not sid:
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "id required"}, "final": True}
            return
        engine = await handlers.ensure_engine()
        s = await storage.get_schedule(engine, sid)
        yield {
            "event": "schedule",
            "data": {"schedule": _schedule_to_dict(s) if s else None},
            "final": True,
        }

    async def schedule_write(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Upsert 一筆 schedule。給 id → update;沒給 → create。"""
        engine = await handlers.ensure_engine()

        # 必填驗證
        name = params.get("name")
        cron_expr = params.get("cron_expr")
        trigger_type = params.get("trigger_type")
        payload = params.get("payload")
        if not all(isinstance(x, str) and x for x in (name, cron_expr, trigger_type, payload)):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "name / cron_expr / trigger_type / payload required"},
                   "final": True}
            return
        assert isinstance(cron_expr, str)
        if trigger_type not in ("skill", "prompt"):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "trigger_type must be 'skill' or 'prompt'"},
                   "final": True}
            return
        if not is_valid_cron(cron_expr):
            yield {"event": "error", "data": {"code": "BAD_CRON",
                   "message": f"invalid cron expression: {cron_expr!r}"},
                   "final": True}
            return

        scope = params.get("scope") if params.get("scope") in ("user", "project") else "user"
        project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
        if scope == "project" and not project_id:
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "project scope requires project_id"},
                   "final": True}
            return
        if scope == "user":
            project_id = None  # 確保 user-scope 不帶 project_id

        enabled = bool(params.get("enabled", True))
        model_provider = params.get("model_provider") if isinstance(params.get("model_provider"), str) else None
        model = params.get("model") if isinstance(params.get("model"), str) else None
        workspace_dir = params.get("workspace_dir") if isinstance(params.get("workspace_dir"), str) else None
        # Loop = bound to 既有 session;有值表示 fire 時送回該 session(不開新)
        target_session_id = params.get("target_session_id") if isinstance(params.get("target_session_id"), str) else None

        # Project-scope 自動帶 workspace_dir
        if scope == "project" and project_id and not workspace_dir:
            proj = await storage.get_project(engine, project_id)
            if proj is not None and proj.workspace_dir:
                workspace_dir = proj.workspace_dir

        nxt = compute_next_run_at(cron_expr) if enabled else None

        sid = params.get("id")
        if isinstance(sid, str) and sid:
            # Update — 暫不支援切換 target_session_id(loop ↔ schedule 不該透過 update)
            existing = await storage.get_schedule(engine, sid)
            if existing is None:
                yield {"event": "error", "data": {"code": "NOT_FOUND",
                       "message": f"schedule {sid!r} not found"}, "final": True}
                return
            await storage.update_schedule(
                engine, sid,
                name=name, cron_expr=cron_expr,
                trigger_type=trigger_type, payload=payload,
                project_id=project_id if scope == "project" else None,
                _clear_project=(scope == "user"),
                enabled=enabled,
                next_run_at=nxt,
                model_provider=model_provider or "",
                model=model or "",
                workspace_dir=workspace_dir or "",
            )
            updated = await storage.get_schedule(engine, sid)
        else:
            assert isinstance(name, str)
            assert isinstance(trigger_type, str)
            assert isinstance(payload, str)
            updated = await storage.create_schedule(
                engine,
                name=name, cron_expr=cron_expr,
                trigger_type=trigger_type, payload=payload,
                project_id=project_id,
                enabled=enabled,
                next_run_at=nxt,
                model_provider=model_provider,
                model=model,
                workspace_dir=workspace_dir,
                target_session_id=target_session_id,
            )

        yield {
            "event": "schedule_written",
            "data": {"schedule": _schedule_to_dict(updated) if updated else None},
            "final": True,
        }

    async def schedule_delete(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("id")
        if not isinstance(sid, str) or not sid:
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "id required"}, "final": True}
            return
        engine = await handlers.ensure_engine()
        ok = await storage.delete_schedule(engine, sid)
        if not ok:
            yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
            return
        yield {"event": "schedule_deleted", "data": {"id": sid}, "final": True}

    async def schedule_run_now(params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("id")
        if not isinstance(sid, str) or not sid:
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "id required"}, "final": True}
            return
        # UI 手動觸發 — fire-and-forget,不擋 RPC return
        engine = await handlers.ensure_engine()
        existing = await storage.get_schedule(engine, sid)
        if existing is None:
            yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
            return
        import asyncio
        asyncio.create_task(handlers._scheduler.run_now(sid))
        yield {"event": "schedule_run_started", "data": {"id": sid}, "final": True}

    return {
        "schedule.list": schedule_list,
        "schedule.get": schedule_get,
        "schedule.write": schedule_write,
        "schedule.delete": schedule_delete,
        "schedule.run_now": schedule_run_now,
    }
