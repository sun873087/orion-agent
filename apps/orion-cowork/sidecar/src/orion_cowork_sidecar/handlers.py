"""RPC method handlers — 連 orion-sdk Conversation。

Phase 31-D 後:對話跨 app restart 保留(本機 SQLite)。
~/.orion-cowork/sessions.db 由 storage.py 管理。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_model.provider import get_provider
from orion_sdk.core.conversation import Conversation
from orion_sdk.core.state import AgentContext
from orion_sdk.services.feature_flags import load_feature_flags
from orion_sdk.tools.builtin_set import build_default_tool_set

from orion_cowork_sidecar import memory_handlers, storage
from orion_cowork_sidecar.desktop_tools import OpenPathTool, OpenUrlTool
from orion_cowork_sidecar.mcp_integration import CoworkMcpManager
from orion_cowork_sidecar.streaming import to_rpc_frame

load_dotenv()


# Cowork 是 desktop 聊天 app — 不該帶 cwd / git_status / env_info(那是給
# CLI 用的)。給個簡短 system prompt,SDK 看到 self.system_prompt 非空就會
# 跳過 fetch_system_prompt_parts,user message 不被 per-turn 注入污染。
COWORK_SYSTEM_PROMPT = (
    "You are a helpful AI assistant inside Orion Cowork — a desktop chat app "
    "running locally on the user's own machine. You have full permission to act "
    "on the user's behalf for things they explicitly ask, including:\n"
    "- Opening URLs in their default browser (use the `open_url` tool)\n"
    "- Opening local files / folders with the OS default app (use `open_path`)\n"
    "- Running shell commands via Bash when they ask you to do something on the system\n"
    "- Reading / writing files in their workspace\n"
    "- Searching the web, fetching pages, analysing attached images\n"
    "\n"
    "When the user attaches images, describe or analyze them as requested. "
    "Do not refuse desktop actions on grounds of 'I can't control your computer' — "
    "you can, that's what the tools above are for. Just do what they asked, then "
    "report what you did."
)


class Handlers:
    """Active Conversation in-memory cache + SQLite persistence。

    Cowork single-user — 用 storage.LOCAL_USER_ID 作 user_id。
    重啟 app 後從 DB resume,跨 restart 對話保留。
    """

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._aborts: dict[str, AgentContext] = {}
        self._engine: AsyncEngine | None = None
        self._engine_lock = asyncio.Lock()
        # in-mem cache for fast title-on-first-prompt(避免每 turn 都打 DB select)
        self._title_done: set[str] = set()
        # Phase 31-D 下:MCP manager(lazy start)
        self._mcp = CoworkMcpManager()
        self._mcp_started = False
        self._mcp_lock = asyncio.Lock()

    async def ensure_engine(self) -> AsyncEngine:
        # 加 lock 避免兩個 concurrent task 都跑 init_db → "table already exists"
        async with self._engine_lock:
            if self._engine is None:
                self._engine = await storage.init_storage()
                # 一次性把 legacy inline base64 ImageBlock 抽進 blob store。
                # idempotent:已是 blob ref 的 row 略過,沒事可做就秒回。
                import sys
                try:
                    stats = await storage.migrate_inline_attachments_to_blobs(
                        self._engine,
                    )
                    if stats["migrated_rows"]:
                        print(
                            f"[storage] migration done: "
                            f"scanned={stats['scanned']} "
                            f"migrated_rows={stats['migrated_rows']} "
                            f"blobs_written={stats['blobs_written']}",
                            file=sys.stderr, flush=True,
                        )
                except Exception as e:  # noqa: BLE001
                    print(
                        f"[storage] migration failed: {e}",
                        file=sys.stderr, flush=True,
                    )
                # GC 一次孤兒 blob — 可能來自之前 delete_session 漏 unlink
                # (這次修以前的 build)或 migration 異常產生的殘留。
                try:
                    cleanup = await storage.cleanup_orphan_blobs(self._engine)
                    if cleanup["deleted"]:
                        print(
                            f"[storage] cleaned {cleanup['deleted']} orphan blobs "
                            f"({cleanup['bytes_freed'] / 1024:.0f} KB)",
                            file=sys.stderr, flush=True,
                        )
                except Exception as e:  # noqa: BLE001
                    print(
                        f"[storage] cleanup failed: {e}",
                        file=sys.stderr, flush=True,
                    )
            return self._engine

    async def ensure_mcp(self) -> CoworkMcpManager:
        """Lazy start McpManager + supervisor — 首次需要 mcp tools 或 mcp.list 時才連。"""
        async with self._mcp_lock:
            if not self._mcp_started:
                try:
                    await self._mcp.start()
                except Exception:  # noqa: BLE001
                    # Start 失敗不該擋 sidecar — 沒 MCP 也能跑 builtin tools
                    pass
                self._mcp_started = True
            return self._mcp

    async def shutdown(self) -> None:
        """sidecar 退出時清理 MCP。"""
        await self._mcp.shutdown()

    # ─── Dispatch table ─────────────────────────────────────────────────
    def methods(self) -> dict[str, Any]:
        return {
            "ping": self.ping,
            "models.list": self.models_list,
            "conversation.create": self.conversation_create,
            "conversation.send": self.conversation_send,
            "conversation.abort": self.conversation_abort,
            "conversation.list": self.conversation_list,
            "conversation.search": self.conversation_search,
            "conversation.delete": self.conversation_delete,
            "conversation.get_workspace": self.conversation_get_workspace,
            "conversation.set_workspace": self.conversation_set_workspace,
            "conversation.set_project": self.conversation_set_project,
            "project.list": self.project_list,
            "project.get": self.project_get,
            "project.create": self.project_create,
            "project.update": self.project_update,
            "project.delete": self.project_delete,
            "memory.list": memory_handlers.memory_list,
            "memory.get": memory_handlers.memory_get,
            "memory.write": memory_handlers.memory_write,
            "memory.delete": memory_handlers.memory_delete,
            "conversation.messages": self.conversation_messages,
            "conversation.attachment": self.conversation_attachment,
            "conversation.regenerate": self.conversation_regenerate,
            "mcp.list": self.mcp_list,
            "mcp.reconnect": self.mcp_reconnect,
            "mcp.config_list": self.mcp_config_list,
            "mcp.config_upsert": self.mcp_config_upsert,
            "mcp.config_delete": self.mcp_config_delete,
            "maintenance.migrate_attachments": self.maintenance_migrate_attachments,
            "maintenance.cleanup_blobs": self.maintenance_cleanup_blobs,
        }

    # ─── Methods ────────────────────────────────────────────────────────
    async def ping(self, _params: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "pong", "final": True}

    async def models_list(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """回 catalog 內所有 provider × model + per-provider API key 是否設定。"""
        import os

        from orion_model.catalog import list_catalog

        catalog = list_catalog()
        # Per-provider API key status — 不外洩 key,只報 "configured" / not。
        env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        # list_catalog() 回 {"providers": [{"id", "label", "models": [...]}, ...]}
        providers = catalog.get("providers", [])
        if isinstance(providers, list):
            for p in providers:
                if not isinstance(p, dict):
                    continue
                env_name = env_map.get(p.get("id", ""))
                p["api_key_configured"] = bool(env_name and os.environ.get(env_name))
        yield {
            "event": "models",
            "data": catalog,
            "final": True,
        }

    async def conversation_create(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        provider_name = params.get("provider", "anthropic")
        model = params.get("model", "claude-sonnet-4-6")
        project_id = params.get("project_id")  # 可選
        workspace_dir = params.get("workspace_dir")  # 可選
        engine = await self.ensure_engine()
        conv, _ext_workspace = await self._build_conversation(
            provider_name=provider_name,
            model=model,
            session_id=None,
            workspace_dir=workspace_dir,
            project_id=project_id,
            state_messages=None,
            engine=engine,
        )
        sid = str(conv.session_id)
        self._conversations[sid] = conv

        await storage.save_session_metadata(
            engine, sid, provider=provider_name, model=model,
        )
        # 寫 cowork-ext (project / workspace) 若有給
        if project_id:
            await storage.set_session_project(engine, sid, project_id)
        if workspace_dir:
            await storage.set_session_workspace(engine, sid, workspace_dir)
        yield {
            "event": "conversation_created",
            "data": {"session_id": sid, "provider": provider_name, "model": model},
            "final": True,
        }

    async def conversation_send(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        prompt = params.get("prompt", "")
        raw_attachments = params.get("attachments") or []
        if sid is None:
            yield {
                "event": "error",
                "data": {"code": "BAD_SESSION_ID", "message": "session_id required"},
                "final": True,
            }
            return

        try:
            UUID(sid)
        except (ValueError, TypeError):
            yield {
                "event": "error",
                "data": {"code": "BAD_SESSION_ID", "message": f"invalid UUID: {sid!r}"},
                "final": True,
            }
            return

        engine = await self.ensure_engine()

        # Lazy resume:若 in-memory cache 沒這 session,從 DB 載入
        conv = self._conversations.get(sid)
        if conv is None:
            conv = await self._resume_from_db(sid, engine)
            if conv is None:
                yield {
                    "event": "error",
                    "data": {"code": "UNKNOWN_SESSION", "message": f"session {sid!r} not found"},
                    "final": True,
                }
                return
            self._conversations[sid] = conv

        # 首次 prompt → 設 title
        if sid not in self._title_done:
            # 用 prompt 文字當 title,empty 時退到「(attachment)」
            title_seed = prompt.strip() or ("(attachment)" if raw_attachments else "")
            if title_seed:
                await storage.update_title_if_empty(engine, sid, title_seed)
                self._title_done.add(sid)

        # 把 attachments 轉成 ImageBlock(預期格式:[{media_type, data: base64}])
        images = []
        # Debug — stderr 印到 Electron main process console;不影響 stdio RPC
        import sys
        print(
            f"[sidecar] conversation.send sid={sid[:8]} prompt={prompt[:30]!r} "
            f"attachments_count={len(raw_attachments)}",
            file=sys.stderr, flush=True,
        )
        if raw_attachments:
            from orion_model.types import ImageBlock
            for i, a in enumerate(raw_attachments):
                if not isinstance(a, dict):
                    print(f"[sidecar]   attachment[{i}] dropped: not a dict (got {type(a).__name__})", file=sys.stderr, flush=True)
                    continue
                media_type = a.get("media_type") or "image/png"
                data = a.get("data")
                if not isinstance(data, str) or not data:
                    print(
                        f"[sidecar]   attachment[{i}] dropped: bad data "
                        f"(type={type(data).__name__}, len={len(data) if isinstance(data,str) else 'N/A'})",
                        file=sys.stderr, flush=True,
                    )
                    continue
                try:
                    images.append(ImageBlock(media_type=media_type, data=data))
                    print(
                        f"[sidecar]   attachment[{i}] OK: {media_type} "
                        f"{len(data)}b base64",
                        file=sys.stderr, flush=True,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[sidecar]   attachment[{i}] ImageBlock build failed: {e}", file=sys.stderr, flush=True)
                    continue
        print(f"[sidecar] -> conv.send with {len(images)} images", file=sys.stderr, flush=True)

        # 記下 turn 開始時的 message 數,結束後 diff append 新訊息進 DB
        before_count = len(conv.state_messages)

        # Workspace / project 設定:有則 ctx.cwd 用 workspace_dir,SDK 看到後就
        # 跑 cwd-derived sections。沒設用 process cwd 但 include_workspace_context=False
        # 仍會被 SDK 忽略。
        ctx_cwd = await self._resolve_session_cwd(sid, engine)
        ctx_kwargs: dict[str, Any] = dict(
            feature_flags=load_feature_flags(),
            user_id=storage.LOCAL_USER_ID,
        )
        if ctx_cwd is not None:
            ctx_kwargs["cwd"] = ctx_cwd
        ctx = AgentContext(**ctx_kwargs)
        self._aborts[sid] = ctx
        try:
            async for ev in conv.send(prompt, ctx=ctx, images=images or None):
                frame = to_rpc_frame(ev)
                if frame is not None:
                    yield frame
        finally:
            self._aborts.pop(sid, None)
            # Persist new messages(只 append 這 turn 增加的)
            new_msgs = conv.state_messages[before_count:]
            if new_msgs:
                try:
                    await storage.append_messages(engine, sid, new_msgs)
                except Exception:  # noqa: BLE001
                    # Persistence 失敗不該炸 sidecar — 之後重 send 還是會嘗試
                    pass

    async def _resolve_session_cwd(
        self, sid: str, engine: AsyncEngine
    ) -> "Path | None":
        """Session 的 effective workspace_dir(session > project > None)→ Path 或 None。"""
        from pathlib import Path
        ext = await storage.get_session_ext(engine, sid)
        ws = ext["workspace_dir"]
        if not ws and ext["project_id"]:
            proj = await storage.get_project(engine, ext["project_id"])
            if proj is not None:
                ws = proj.workspace_dir
        return Path(ws) if ws else None

    async def _build_conversation(
        self,
        *,
        provider_name: str,
        model: str,
        session_id: str | None,
        workspace_dir: str | None,
        project_id: str | None,
        state_messages: list[Any] | None,
        engine: AsyncEngine,
    ) -> tuple[Conversation, str | None]:
        """集中 Cowork Conversation 建構邏輯:吸收 workspace + project 設定。

        回 (conv, effective_workspace_dir)。effective_workspace_dir 是
        實際傳給 ctx.cwd 的目錄(session-level > project-level > None)。
        """
        from uuid import UUID as _UUID

        from orion_model.provider import get_provider

        llm = get_provider(provider_name, model)
        mcp = await self.ensure_mcp()
        tools = (
            build_default_tool_set(asker=None)
            + [OpenUrlTool(), OpenPathTool()]
            + mcp.tools
        )

        # Resolve workspace_dir + custom_instructions:
        # session-level workspace > project-level workspace > None
        # project-level custom_instructions 注入 system_prompt 後
        effective_workspace: str | None = workspace_dir
        project_custom_instructions: str | None = None
        if project_id:
            proj = await storage.get_project(engine, project_id)
            if proj is not None:
                if not effective_workspace and proj.workspace_dir:
                    effective_workspace = proj.workspace_dir
                project_custom_instructions = proj.custom_instructions

        system_prompt = COWORK_SYSTEM_PROMPT
        if project_custom_instructions:
            system_prompt = (
                COWORK_SYSTEM_PROMPT
                + "\n\n# Project instructions\n\n"
                + project_custom_instructions
            )

        include_ws = bool(effective_workspace)

        conv_kwargs: dict[str, Any] = dict(
            provider=llm,
            tools=tools,
            persistence_enabled=False,
            user_id=storage.LOCAL_USER_ID,
            memory_enabled=True,
            auto_extract_memories=True,
            include_workspace_context=include_ws,
            include_env_info=True,
            system_prompt=system_prompt,
        )
        if session_id is not None:
            conv_kwargs["session_id"] = _UUID(session_id)
        conv = Conversation(**conv_kwargs)
        if state_messages is not None:
            conv.state_messages = state_messages
        return conv, effective_workspace

    async def _resume_from_db(
        self, sid: str, engine: AsyncEngine
    ) -> Conversation | None:
        """從 DB 載入既有對話,重建 Conversation in-memory(吸收 ext / project)。"""
        sessions = await storage.list_sessions(engine)
        match = next((s for s in sessions if s.session_id == sid), None)
        if match is None:
            return None
        ext = await storage.get_session_ext(engine, sid)
        state_messages = await storage.load_messages(engine, sid)
        conv, _ = await self._build_conversation(
            provider_name=match.provider,
            model=match.model,
            session_id=sid,
            workspace_dir=ext["workspace_dir"],
            project_id=ext["project_id"],
            state_messages=state_messages,
            engine=engine,
        )
        if conv.state_messages:
            self._title_done.add(sid)
        return conv

    async def conversation_abort(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        ctx = self._aborts.get(sid or "")
        if ctx is None:
            yield {
                "event": "no_active_turn",
                "data": {"session_id": sid},
                "final": True,
            }
            return
        ctx.abort_event.set()
        # Give the loop a chance to observe the abort
        await asyncio.sleep(0)
        yield {"event": "abort_requested", "data": {"session_id": sid}, "final": True}

    async def conversation_list(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """從 DB 列當前 user 所有對話(by created_at desc)。"""
        engine = await self.ensure_engine()
        rows = await storage.list_sessions(engine)
        yield {
            "event": "conversation_list",
            "data": {
                "sessions": [
                    {
                        "session_id": r.session_id,
                        "provider": r.provider,
                        "model": r.model,
                        "title": r.title,
                        "created_at": r.created_at,
                        "n_messages": r.n_messages,
                    }
                    for r in rows
                ],
            },
            "final": True,
        }

    async def conversation_search(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """跨 session 全文搜尋:title + message text + tool result。

        in-memory 比對(對單機 sessions 規模夠用),回 [{session_id, title,
        snippet, match_count, ...}]。
        """
        query = str(params.get("query") or "").strip()
        if not query:
            yield {
                "event": "conversation_search_result",
                "data": {"query": query, "sessions": []},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        hits = await storage.search_messages(engine, query)
        yield {
            "event": "conversation_search_result",
            "data": {
                "query": query,
                "sessions": [
                    {
                        "session_id": h.session_id,
                        "title": h.title,
                        "provider": h.provider,
                        "model": h.model,
                        "created_at": h.created_at,
                        "match_count": h.match_count,
                        "snippet": h.snippet,
                    }
                    for h in hits
                ],
            },
            "final": True,
        }

    # ─── Workspace / Project methods ────────────────────────────────────

    async def conversation_get_workspace(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        if not isinstance(sid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        ext = await storage.get_session_ext(engine, sid)
        yield {
            "event": "session_ext",
            "data": {
                "session_id": sid,
                "workspace_dir": ext["workspace_dir"],
                "project_id": ext["project_id"],
            },
            "final": True,
        }

    async def conversation_set_workspace(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        ws = params.get("workspace_dir")
        if not isinstance(sid, str) or (ws is not None and not isinstance(ws, str)):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        await storage.set_session_workspace(engine, sid, ws or None)
        # 既有 in-memory conv 失效,下次 send 會 resume 帶新 ext
        self._conversations.pop(sid, None)
        yield {
            "event": "session_ext",
            "data": {"session_id": sid, "workspace_dir": ws or None},
            "final": True,
        }

    async def conversation_set_project(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        pid = params.get("project_id")
        if not isinstance(sid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        if pid is not None and not isinstance(pid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        await storage.set_session_project(engine, sid, pid or None)
        self._conversations.pop(sid, None)
        yield {
            "event": "session_ext",
            "data": {"session_id": sid, "project_id": pid or None},
            "final": True,
        }

    async def project_list(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        engine = await self.ensure_engine()
        projects = await storage.list_projects(engine)
        yield {
            "event": "project_list",
            "data": {"projects": [self._project_to_dict(p) for p in projects]},
            "final": True,
        }

    async def project_get(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        pid = params.get("project_id")
        if not isinstance(pid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        proj = await storage.get_project(engine, pid)
        if proj is None:
            yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
            return
        sessions = await storage.list_sessions_in_project(engine, pid)
        yield {
            "event": "project",
            "data": {
                "project": self._project_to_dict(proj),
                "session_ids": sessions,
            },
            "final": True,
        }

    async def project_create(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "name required"}, "final": True}
            return
        engine = await self.ensure_engine()
        proj = await storage.create_project(
            engine,
            name=name.strip(),
            description=params.get("description") or None,
            workspace_dir=params.get("workspace_dir") or None,
            custom_instructions=params.get("custom_instructions") or None,
        )
        yield {
            "event": "project",
            "data": {"project": self._project_to_dict(proj)},
            "final": True,
        }

    async def project_update(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        pid = params.get("project_id")
        if not isinstance(pid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        ok = await storage.update_project(
            engine,
            pid,
            name=params.get("name"),
            description=params.get("description"),
            workspace_dir=params.get("workspace_dir"),
            custom_instructions=params.get("custom_instructions"),
        )
        # 既有屬於此 project 的 in-memory conv 失效,下次 send 重 build
        if ok:
            for sid in list(self._conversations.keys()):
                ext = await storage.get_session_ext(engine, sid)
                if ext["project_id"] == pid:
                    self._conversations.pop(sid, None)
        yield {
            "event": "project_updated",
            "data": {"project_id": pid, "ok": ok},
            "final": True,
        }

    async def project_delete(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        pid = params.get("project_id")
        if not isinstance(pid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        ok = await storage.delete_project(engine, pid)
        # 既有 conv 失效
        for sid in list(self._conversations.keys()):
            self._conversations.pop(sid, None)
        yield {
            "event": "project_deleted",
            "data": {"project_id": pid, "ok": ok},
            "final": True,
        }

    @staticmethod
    def _project_to_dict(p: "storage.Project") -> dict[str, Any]:
        return {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "workspace_dir": p.workspace_dir,
            "custom_instructions": p.custom_instructions,
            "created_at": p.created_at,
        }

    async def conversation_delete(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        if sid is None:
            yield {
                "event": "error",
                "data": {"code": "BAD_SESSION_ID", "message": "session_id required"},
                "final": True,
            }
            return

        engine = await self.ensure_engine()

        # 中止 in-flight turn(若有)
        ctx = self._aborts.get(sid)
        if ctx is not None:
            ctx.abort_event.set()
        self._conversations.pop(sid, None)
        self._aborts.pop(sid, None)
        self._title_done.discard(sid)

        ok = await storage.delete_session(engine, sid)
        if not ok:
            yield {
                "event": "error",
                "data": {"code": "UNKNOWN_SESSION", "message": f"session {sid!r} not found"},
                "final": True,
            }
            return
        yield {
            "event": "conversation_deleted",
            "data": {"session_id": sid},
            "final": True,
        }

    # ─── MCP methods ────────────────────────────────────────────────────

    async def mcp_list(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """列當前 mcp.json 內每個 server 的 connection status + tools。"""
        mcp = await self.ensure_mcp()
        statuses = mcp.list_status()
        from orion_cowork_sidecar.mcp_integration import cowork_mcp_config_path
        yield {
            "event": "mcp_list",
            "data": {
                "config_path": str(cowork_mcp_config_path()),
                "servers": [
                    {
                        "name": s.name,
                        "status": s.status,
                        "error": s.error,
                        "tools": s.tools,
                    }
                    for s in statuses
                ],
            },
            "final": True,
        }

    async def mcp_config_list(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """讀 mcp.json 全部 server raw config(給 UI 編輯用)。"""
        from orion_cowork_sidecar.mcp_integration import (
            cowork_mcp_config_path,
            read_mcp_config_raw,
        )
        servers = read_mcp_config_raw()
        yield {
            "event": "mcp_config_list",
            "data": {
                "config_path": str(cowork_mcp_config_path()),
                "servers": [
                    {"name": name, "config": cfg}
                    for name, cfg in servers.items()
                ],
            },
            "final": True,
        }

    async def mcp_config_upsert(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """新增 / 更新一筆 server。寫 mcp.json 後 reload manager。

        params:
          - name: 必填
          - config: 必填 dict,含 type=stdio|http + (command/args/env or url/headers)
          - rename_from: 可選,原 name(改名時舊 entry 一起刪)
        """
        from orion_cowork_sidecar.mcp_integration import (
            read_mcp_config_raw,
            write_mcp_config_raw,
        )
        name = params.get("name")
        config = params.get("config")
        rename_from = params.get("rename_from")
        if not isinstance(name, str) or not name.strip():
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "name required"}, "final": True}
            return
        if not isinstance(config, dict):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "config must be dict"}, "final": True}
            return
        # 基本 schema 檢驗 — type 必填
        t = config.get("type", "stdio")
        if t not in ("stdio", "http"):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": f"unknown type: {t}"}, "final": True}
            return
        if t == "stdio" and not isinstance(config.get("command"), str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "stdio config needs command"}, "final": True}
            return
        if t == "http" and not isinstance(config.get("url"), str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "http config needs url"}, "final": True}
            return

        servers = read_mcp_config_raw()
        if isinstance(rename_from, str) and rename_from and rename_from != name:
            servers.pop(rename_from, None)
        servers[name.strip()] = config
        write_mcp_config_raw(servers)
        # reload manager 讓變更生效(若 mcp 還沒 start,reload 內 start 也會跑)
        await self._mcp.reload()
        self._mcp_started = True
        yield {
            "event": "mcp_config_upserted",
            "data": {"name": name.strip()},
            "final": True,
        }

    async def mcp_config_delete(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        from orion_cowork_sidecar.mcp_integration import (
            read_mcp_config_raw,
            write_mcp_config_raw,
        )
        name = params.get("name")
        if not isinstance(name, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        servers = read_mcp_config_raw()
        if name not in servers:
            yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
            return
        servers.pop(name)
        write_mcp_config_raw(servers)
        await self._mcp.reload()
        self._mcp_started = True
        yield {
            "event": "mcp_config_deleted",
            "data": {"name": name},
            "final": True,
        }

    async def mcp_reconnect(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """手動觸發 reconnect 某個 server。"""
        name = params.get("name")
        if not name:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "name required"},
                "final": True,
            }
            return
        mcp = await self.ensure_mcp()
        ok = await mcp.reconnect(name)
        yield {
            "event": "mcp_reconnect_result",
            "data": {"name": name, "ok": ok},
            "final": True,
        }

    # ─── Conversation history methods ─────────────────────────────────

    async def conversation_messages(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """從 DB 載指定 session 的 messages,轉成 renderer-friendly UI format。

        Output format(per message):
            {role, text, attachments?: [{media_type, data_url}], created_at}
        """
        sid = params.get("session_id")
        if sid is None:
            yield {
                "event": "error",
                "data": {"code": "BAD_SESSION_ID", "message": "session_id required"},
                "final": True,
            }
            return
        try:
            UUID(sid)
        except (ValueError, TypeError):
            yield {
                "event": "error",
                "data": {"code": "BAD_SESSION_ID", "message": f"invalid UUID: {sid!r}"},
                "final": True,
            }
            return

        engine = await self.ensure_engine()
        # UI lightweight 路徑:讀 raw rows,不 hydrate image blob bytes。
        # ImageBlock 在 content_json 內已只有 ref(migration 完成後),
        # 切歷史 SELECT 只撈 KB-level rows,瞬間。
        raw_rows = await storage.load_raw_messages(engine, sid)
        ui_messages = _to_ui_messages_from_raw(raw_rows)

        yield {
            "event": "conversation_messages",
            "data": {"session_id": sid, "messages": ui_messages},
            "final": True,
        }

    async def maintenance_migrate_attachments(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """手動觸發 inline base64 → blob 抽離。

        啟動時已 auto run 一次;這 RPC 給之後想再跑或從 UI 觸發 progress 顯示用。
        """
        engine = await self.ensure_engine()
        stats = await storage.migrate_inline_attachments_to_blobs(engine)
        yield {
            "event": "migration_done",
            "data": stats,
            "final": True,
        }

    async def maintenance_cleanup_blobs(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """掃孤兒 blob 並 unlink — 啟動時自動跑,這 RPC 給之後手動觸發用。"""
        engine = await self.ensure_engine()
        stats = await storage.cleanup_orphan_blobs(engine)
        yield {
            "event": "cleanup_done",
            "data": stats,
            "final": True,
        }

    async def conversation_attachment(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Lazy 拿單張 attachment 的 data_url。

        Renderer 在 message 上看到 attachment ref(message_index, attachment_index)
        才呼這個拿 base64。整段 history 不再一次背所有 base64,大幅降低
        切換歷史對話的 latency。
        """
        sid = params.get("session_id")
        msg_idx_raw = params.get("message_index")
        att_idx_raw = params.get("attachment_index")
        if sid is None or msg_idx_raw is None or att_idx_raw is None:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS",
                         "message": "session_id, message_index, attachment_index required"},
                "final": True,
            }
            return
        try:
            UUID(sid)
            msg_idx = int(msg_idx_raw)
            att_idx = int(att_idx_raw)
        except (ValueError, TypeError):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "invalid params"},
                "final": True,
            }
            return

        engine = await self.ensure_engine()
        # storage helper 內部:讀 raw row → 找對應 ImageBlock dict → 優先讀 blob,
        # fallback inline base64(legacy migration 前的舊資料)。
        try:
            data_url = await storage.read_attachment_data_url(
                engine, sid, msg_idx, att_idx,
            )
        except (IndexError, ValueError, FileNotFoundError) as e:
            yield {
                "event": "error",
                "data": {"code": "NOT_FOUND", "message": str(e)},
                "final": True,
            }
            return
        # media_type 從 data URL 開頭擷
        media_type = data_url.split(";", 1)[0].removeprefix("data:") or "image/png"
        yield {
            "event": "conversation_attachment",
            "data": {
                "session_id": sid,
                "message_index": msg_idx,
                "attachment_index": att_idx,
                "media_type": media_type,
                "data_url": data_url,
            },
            "final": True,
        }

    async def conversation_regenerate(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """重新生成最後一個 assistant turn。

        步驟:
          1. truncate state_messages 退回到「最後一個 user message 之前」
             (保留該 user message,把後面的 assistant + tool result 都丟)
          2. 持久層也同步 — 用 transaction delete 對應 message rows
          3. 重新跑 query_loop (Conversation.send 不會 append user msg 因為
             我們手動把它 keep 在 state_messages 內;這邊改 call provider 直接)

        實作簡化:用 SDK Conversation 跑一個無實質 user_text 的 send。但
        send 預設 append user msg。所以這裡 manual 重 query — 把 state
        cut 後直接 call Conversation 內部 query_loop。

        Phase 31-D 簡化版:從最後一個 user msg 的 text 重 send。把那個 user
        msg + 之後全砍,當作沒送過,從原 text 重新呼 send。
        """
        sid = params.get("session_id")
        if sid is None:
            yield {
                "event": "error",
                "data": {"code": "BAD_SESSION_ID", "message": "session_id required"},
                "final": True,
            }
            return

        engine = await self.ensure_engine()
        conv = self._conversations.get(sid)
        if conv is None:
            conv = await self._resume_from_db(sid, engine)
            if conv is None:
                yield {
                    "event": "error",
                    "data": {"code": "UNKNOWN_SESSION", "message": f"session {sid!r} not found"},
                    "final": True,
                }
                return
            self._conversations[sid] = conv

        # 找最後一個 user message
        msgs = conv.state_messages
        last_user_idx = -1
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].role == "user":
                last_user_idx = i
                break
        if last_user_idx < 0:
            yield {
                "event": "error",
                "data": {"code": "NO_USER_MESSAGE", "message": "no user message to regenerate from"},
                "final": True,
            }
            return

        # 抓回 user message 的 text + images
        last_user_msg = msgs[last_user_idx]
        regen_text = ""
        regen_images: list[Any] = []
        content = last_user_msg.content
        if isinstance(content, str):
            regen_text = content
        else:
            from orion_model.types import ImageBlock, TextBlock
            for block in content:
                if isinstance(block, TextBlock):
                    regen_text += block.text
                elif isinstance(block, ImageBlock):
                    regen_images.append(block)

        # Truncate in-memory state(回到 user msg 之前)
        conv.state_messages = msgs[:last_user_idx]

        # 持久層也 truncate(從 last_user 以後 delete)
        from sqlalchemy import delete, select

        from orion_sdk.storage.db.engine import db_session
        from orion_sdk.storage.db.models import Message as MessageRow

        async with db_session(engine) as s:
            rows = list((await s.execute(
                select(MessageRow.id, MessageRow.created_at)
                .where(MessageRow.session_id == sid)
                .order_by(MessageRow.created_at, MessageRow.id)
            )).all())
            # 砍從 last_user_idx 開始(包括)的所有 rows
            to_remove = rows[last_user_idx:]
            for row_id, _ in to_remove:
                await s.execute(delete(MessageRow).where(MessageRow.id == row_id))
            await s.commit()

        # Re-send the user prompt(會再 append + persist 新 messages)
        before_count = len(conv.state_messages)
        ctx_cwd = await self._resolve_session_cwd(sid, engine)
        ctx_kwargs: dict[str, Any] = dict(
            feature_flags=load_feature_flags(),
            user_id=storage.LOCAL_USER_ID,
        )
        if ctx_cwd is not None:
            ctx_kwargs["cwd"] = ctx_cwd
        ctx = AgentContext(**ctx_kwargs)
        self._aborts[sid] = ctx
        try:
            async for ev in conv.send(regen_text, ctx=ctx, images=regen_images or None):
                frame = to_rpc_frame(ev)
                if frame is not None:
                    yield frame
        finally:
            self._aborts.pop(sid, None)
            new_msgs = conv.state_messages[before_count:]
            if new_msgs:
                try:
                    await storage.append_messages(engine, sid, new_msgs)
                except Exception:  # noqa: BLE001
                    pass


def _to_ui_messages_from_raw(rows: "list[tuple[str, Any]]") -> list[dict[str, Any]]:
    """Raw (role, content_json) → UI dict,不 hydrate image blob bytes。

    走這條 path 切歷史對話完全不打 file system,所有 image 都送 ref 給 renderer
    讓它自己 lazy load。
    """
    out: list[dict[str, Any]] = []
    for msg_idx, (role, content_json) in enumerate(rows):
        text = ""
        attachments: list[dict[str, Any]] = []
        if isinstance(content_json, str):
            text = content_json
        elif isinstance(content_json, list):
            att_idx = 0
            for b in content_json:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
                if btype == "text":
                    text += b.get("text", "")
                elif btype == "image":
                    attachments.append({
                        "media_type": b.get("media_type") or "image/png",
                        "ref": {
                            "message_index": msg_idx,
                            "attachment_index": att_idx,
                        },
                    })
                    att_idx += 1
                # tool_use / tool_result / thinking / tombstone 不出現在 UI
        if not text and not attachments:
            continue
        out.append({
            "role": role,
            "text": text,
            "attachments": attachments,
            "message_index": msg_idx,
        })
    return out


def _to_ui_messages(messages: "list[Any]") -> list[dict[str, Any]]:
    """SDK NormalizedMessage → renderer UI Message dict。

    Phase 31-D 慢載入修:attachment 不 inline base64,只送 ref
    (message_index, attachment_index),renderer 用 `conversation.attachment`
    lazy fetch。整個 history 不再背 5MB+ × N 張的 base64。

    Per message: { role, text, attachments?: [{ media_type, ref: {message_index, attachment_index} }] }
    """
    from orion_model.types import ImageBlock, TextBlock

    out: list[dict[str, Any]] = []
    for msg_idx, m in enumerate(messages):
        role = m.role
        text = ""
        attachments: list[dict[str, Any]] = []
        content = m.content
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            att_idx = 0
            for block in content:
                if isinstance(block, TextBlock):
                    text += block.text
                elif isinstance(block, ImageBlock):
                    attachments.append({
                        "media_type": block.media_type,
                        "ref": {
                            "message_index": msg_idx,
                            "attachment_index": att_idx,
                        },
                    })
                    att_idx += 1
        if not text and not attachments:
            continue  # 跳過純 tool_use / tool_result 訊息
        out.append({
            "role": role,
            "text": text,
            "attachments": attachments,
            # message_index 給 renderer 之後 lazy fetch 用 (跟 ref.message_index 一致)
            "message_index": msg_idx,
        })
    return out
