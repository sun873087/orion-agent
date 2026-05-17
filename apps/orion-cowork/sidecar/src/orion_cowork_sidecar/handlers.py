"""RPC method handlers — 連 orion-sdk Conversation。

Phase 31-D 後:對話跨 app restart 保留(本機 SQLite)。
~/.orion-cowork/sessions.db 由 storage.py 管理。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_model.provider import get_provider
from orion_sdk.core.conversation import Conversation
from orion_sdk.core.state import AgentContext
from orion_sdk.permissions.decisions import (
    PermissionDecision,
    PermissionResult,
    current_tool_use_id,
)
from orion_sdk.services.feature_flags import load_feature_flags
from orion_sdk.tools.builtin_set import build_default_tool_set

from orion_cowork_sidecar import (
    memory_handlers,
    permissions as perm_mod,
    skill_handlers,
    storage,
    stt_handlers,
)
from orion_cowork_sidecar.desktop_tools import OpenPathTool, OpenUrlTool
from orion_cowork_sidecar.mcp_integration import CoworkMcpManager
from orion_cowork_sidecar.streaming import to_rpc_frame

load_dotenv()


# Cowork 是 desktop 聊天 app — 不該帶 cwd / git_status / env_info(那是給
# CLI 用的)。給個簡短 system prompt,SDK 看到 self.system_prompt 非空就會
# 跳過 fetch_system_prompt_parts,user message 不被 per-turn 注入污染。
_COWORK_PROMPT_BASE = (
    "You are a helpful AI assistant inside Orion Cowork — a desktop chat app "
    "running locally on the user's own machine. You have full permission to act "
    "on the user's behalf for things they explicitly ask, including:\n"
    "- Opening URLs in their default browser (use the `open_url` tool)\n"
    "- Opening local files / folders with the OS default app (use `open_path`)\n"
    "- Running shell commands via Bash when they ask you to do something on the system\n"
    "- Reading / writing files in their workspace\n"
    "- Searching the web, fetching pages, analysing attached images\n"
    "\n"
    "Cowork stores everything under `~/.orion-cowork/`, **NOT** `~/.orion/` "
    "(that one belongs to the CLI and chat-api).\n"
    "\n"
    "When the user attaches images, describe or analyze them as requested. "
    "Do not refuse desktop actions on grounds of 'I can't control your computer' — "
    "you can, that's what the tools above are for. Just do what they asked, then "
    "report what you did.\n"
    "\n"
    "# Match effort to the request\n"
    "Calibrate how much you do to what was actually asked:\n"
    "- Pure conversational messages (greetings like 'hi', 'thanks', simple "
    "  chit-chat, single factual questions you can answer from your own "
    "  knowledge) — JUST REPLY. Do NOT call TodoWrite, AskUserQuestion, web "
    "  search, or any other tool. Tools are for actual work.\n"
    "- Genuine multi-step tasks (2+ distinct actions like 'plan → write → "
    "  run → verify', 'install dep → generate file → open it') — call "
    "  `TodoWrite` FIRST with the full plan, then update items as you progress "
    "  (pending → in_progress → completed). Skip TodoWrite for one-shot work.\n"
    "- Ambiguous requests with clear branching options — use "
    "  `AskUserQuestion` ONLY when you can't reasonably pick a default. "
    "  Don't ask just to be polite."
)


# Permission mode 指引 — 由 SDK 的 custom_instructions_conversation 欄位帶進
# system Element 1(BP 2),mode 固定 → session 內 BP 2 byte-identical 享 cache。
# 切 mode 才會讓 BP 2 重寫一次(~5k tokens × 1.25),通常仍比每 turn 在
# BP 4 重複帶 mode prefix(每 turn 250 tokens × 1.25)更省。
_ASK_MODE_INSTRUCTIONS = (
    "## Permission mode: Ask\n"
    "\n"
    "Two strict rules that override your default behavior:\n"
    "\n"
    "1. **Tool approval** — before each side-effecting tool call (Bash, "
    "Write, Edit, web fetch, MCP actions, etc.), the UI shows the user an "
    "approval banner. You just call the tool as usual; the platform pauses "
    "and resumes for you. Do not type 'I'm about to run X, ok?' first — "
    "just call the tool and the banner appears.\n"
    "\n"
    "2. **Clarifying questions MUST use the AskUserQuestion tool, NOT plain "
    "text.** If you need to confirm parameters, ask the user to pick "
    "between options, or gather multiple inputs before executing a task — "
    "you MUST call `AskUserQuestion` with one question per call (max 4 in "
    "a batch). The UI renders clickable option buttons + free-text input, "
    "which is the entire point of Ask mode. Writing a numbered list of "
    "questions in plain text bypasses this UI and is incorrect behavior.\n"
    "\n"
    "Examples of when to use AskUserQuestion:\n"
    "- 'Which format do you want?' with options [PDF, DOCX, Markdown]\n"
    "- 'What should the filename be?' (open-ended, no options)\n"
    "- 'Should I open the file after creating it?' with options [Yes, No]\n"
    "\n"
    "Do NOT use AskUserQuestion for: greetings, small talk, or when a "
    "reasonable default exists and the user hasn't expressed a preference."
)
_ACT_MODE_INSTRUCTIONS = (
    "## Permission mode: Act\n"
    "\n"
    "Proceed autonomously. Do NOT ask clarifying questions — neither via "
    "the AskUserQuestion tool nor in plain text. If parameters are "
    "uncertain, pick the most reasonable default, state your choice "
    "briefly in your response, and continue executing. Only stop on hard "
    "blockers that genuinely cannot be resolved without user input."
)


_SYSTEM_LEVEL_NOTE = (
    "\n\n# System-level (Cowork-wide, not personal nor project)\n"
    "`~/.orion-cowork/skills/` exists for skills that should outlast / cross "
    "the personal vs project distinction. **Do not use this scope unless the "
    "user explicitly says 'system level' / 'app-wide' / 'system 級'** — "
    "default to personal or project."
)


def _paths_section(workspace_dir: str | None, in_project: bool) -> str:
    """根據是否在 project 內,組 context-aware 的目錄表 — 讓 LLM 預設用對的 scope。"""
    if in_project and workspace_dir:
        ws = workspace_dir.rstrip("/")
        return (
            "\n\n# This chat is inside a project — workspace:\n"
            f"  `{ws}`\n"
            "When the user mentions 'skill / memory / mcp library' or 'this "
            "project's …', use the **project-scoped** paths first:\n"
            f"- Project skills:        `{ws}/.orion-cowork/skills/`\n"
            f"- Project memory:        `{ws}/.orion-cowork/memory/`\n"
            f"- Project MCP config:    `{ws}/.orion-cowork/mcp.json`\n"
            f"- Project instructions:  `{ws}/.orion-cowork/instructions.md`\n"
            "Personal libraries still exist at "
            "`~/.orion-cowork/users/cowork-local/{skills,memory}/` and "
            "`~/.orion-cowork/mcp.json`, but **only use them if the user "
            "explicitly says 'personal' / 'app-level' / 'global'**."
        ) + _SYSTEM_LEVEL_NOTE
    return (
        "\n\n# This is a personal chat (not in a project)\n"
        "Use the personal libraries — that's the only scope here:\n"
        "- Personal skills:  `~/.orion-cowork/users/cowork-local/skills/`\n"
        "- Personal memory:  `~/.orion-cowork/users/cowork-local/memory/`\n"
        "- Personal MCP:     `~/.orion-cowork/mcp.json`\n"
        "- Default workspace `~/.orion-cowork/users/cowork-local/workspace/` "
        "(this is the cwd for personal chats; files you create can live here)."
    ) + _SYSTEM_LEVEL_NOTE


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
        # Pending tool-approval futures — Ask 模式下,can_use_tool 把 future
        # 註冊到這,等 renderer 透過 conversation.tool_approval RPC resolve。
        # Key 是 tool_use_id(每個 LLM tool call 一個唯一 id)。
        self._approvals: dict[str, asyncio.Future[PermissionResult]] = {}
        # Pending AskUserQuestion futures — asker 推 frame 後 await 這 future
        # 等 renderer 透過 conversation.ask_user_reply RPC resolve。
        # Key 是 sidecar-generated request_id。
        self._ask_pending: dict[str, asyncio.Future[dict[str, str]]] = {}
        # Per-session 當前 permission_mode — turn 開始時寫入,can_use_tool 每次
        # invocation 都讀 live 值,讓 user 中途切 mode 立刻生效。
        self._session_modes: dict[str, str] = {}

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
            "skill.list": skill_handlers.skill_list,
            "skill.get": skill_handlers.skill_get,
            "skill.write": skill_handlers.skill_write,
            "skill.delete": skill_handlers.skill_delete,
            "prefs.get_all": self.prefs_get_all,
            "prefs.set": self.prefs_set,
            "conversation.messages": self.conversation_messages,
            "conversation.attachment": self.conversation_attachment,
            "conversation.regenerate": self.conversation_regenerate,
            "conversation.truncate": self.conversation_truncate,
            "conversation.tool_approval": self.conversation_tool_approval,
            "conversation.ask_user_reply": self.conversation_ask_user_reply,
            "conversation.set_permission_mode": self.conversation_set_permission_mode,
            "conversation.stats": self.conversation_stats,
            "conversation.context_breakdown": self.conversation_context_breakdown,
            "conversation.compact": self.conversation_compact,
            "permissions.get": self.permissions_get,
            "permissions.set": self.permissions_set,
            "stt.transcribe": stt_handlers.stt_transcribe,
            "stt.status": self.stt_status,
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
        # B2:project 若有自己的 mcp.json,reload manager 拿到 project servers
        await self._sync_mcp_for_session(sid, engine)
        ctx_kwargs: dict[str, Any] = dict(
            feature_flags=load_feature_flags(),
            user_id=storage.LOCAL_USER_ID,
        )
        if ctx_cwd is not None:
            ctx_kwargs["cwd"] = ctx_cwd
        ctx = AgentContext(**ctx_kwargs)
        self._aborts[sid] = ctx

        # ─── permission_mode wiring(Ask vs Act)────────────────────────
        permission_mode = params.get("permission_mode", "act")
        # 寫入 per-session live state — can_use_tool 每次 call 都讀 latest,
        # user 中途切 mode 立刻生效。
        self._session_modes[sid] = permission_mode
        # Frame queue:can_use_tool 在 conv.send 內 await,沒法自己 yield
        # frame。改把 approval-request frame 推 queue,outer loop multiplex
        # 從 queue + conv.send 兩邊收 frame。
        out_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        # Permission policy:每次 can_use_tool 進來都 reload — 讓 banner 的
        # 「永遠允許」按鈕加 rule 後同 turn 後續 tool 立即生效,不必等下個 turn。
        # File I/O 很便宜(小 JSON),per-call 沒 perf 顧慮。
        from pathlib import Path as _P
        ws_for_policy = _P(ctx_cwd) if ctx_cwd else None
        conv.can_use_tool = self._build_can_use_tool(sid, out_queue, ws_for_policy)

        # ─── AskUserQuestion asker wiring(cache-friendly mode design)──
        # Mode 指引走 SDK 的 custom_instructions_conversation → system Element 1 → BP 2
        # 1. system Element 0 永遠 byte-identical(_COWORK_PROMPT_BASE 等)
        # 2. system Element 1 含 mode 指引 — 同 mode 連續 turn 都 hit BP 2;
        #    切 mode 那 turn BP 2 重寫,之後又穩定
        # 3. conv.tools byte-identical(AskUserQuestion 永遠在)
        # 4. Mode 行為差異走 asker callback 動態 dispatch:
        #    - Ask 模式 → 推 ask_user_question frame 等 user reply
        #    - Act 模式 → auto-decide asker 回個 hint 給 LLM 自己 decide
        for tool in conv.tools:
            if getattr(tool, "name", None) == "AskUserQuestion":
                tool.asker = self._build_mode_aware_asker(sid, out_queue)
                tool.should_defer = False
                break

        # 把 mode 指引塞 SDK 的 custom_instructions_conversation,assembler 會
        # 把它包進 system Element 1(BP 2 cache zone)。下次 send 同 mode 仍命中。
        conv.custom_instructions_conversation = (
            _ASK_MODE_INSTRUCTIONS if permission_mode == "ask" else _ACT_MODE_INSTRUCTIONS
        )

        # ─── Auto-compact gate ─────────────────────────────────────────────
        # Renderer 把使用者設定值連 send 一起送上來:enabled + threshold(0.1~0.99)
        # + locale(摘要要用的語系,讓 summary card 跟 UI 一致)。
        auto_compact_enabled = bool(params.get("auto_compact_enabled", True))
        ac_threshold_raw = params.get("auto_compact_threshold")
        if isinstance(ac_threshold_raw, (int, float)):
            conv.auto_compact_threshold = float(ac_threshold_raw)
        locale_raw = params.get("locale")
        if isinstance(locale_raw, str) and locale_raw:
            conv.compact_summary_locale = locale_raw
        # Summary model override:若有,build 便宜 model 的 provider 給 SDK 用
        # (跟 chat provider 區隔,讓摘要 cost 降下來)。建失敗 fallback chat model。
        _apply_summary_provider(conv, params)
        if auto_compact_enabled:
            pre_compact_state_count = len(conv.state_messages)
            try:
                pre_result = await conv.compact(force=False)
            except Exception as e:  # noqa: BLE001
                pre_result = None
                print(f"[sidecar] auto-compact failed: {e}", file=sys.stderr, flush=True)
            if pre_result is not None and pre_result.was_compacted:
                # DB soft-delete:把前 N 筆 row 標 compacted_out + append tombstone。
                # 舊訊息 row 留著,UI scroll 回頭仍看得到(灰化顯示),LLM resume 跳過。
                # N = 原 state_messages 長度 - (新長度 - 1)  // -1 扣掉 tombstone 本身
                kept = pre_result.kept_message_count
                compacted_count = pre_compact_state_count - (kept - 1)
                tombstone_msg = conv.state_messages[0]
                try:
                    await storage.record_compaction(
                        engine, sid,
                        compacted_count=compacted_count,
                        tombstone_msg=tombstone_msg,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[sidecar] auto-compact DB sync failed: {e}", file=sys.stderr, flush=True)
                # before_count 跟著歸零 — 後續 turn append 對齊新 DB 狀態
                before_count = len(conv.state_messages)
                yield {
                    "event": "compact_complete",
                    "data": {
                        "summary": pre_result.summary,
                        "before_tokens": pre_result.before_tokens,
                        "after_tokens": pre_result.after_tokens,
                        "compacted_count": compacted_count,
                        "auto": True,
                    },
                }

        async def _producer() -> None:
            try:
                async for ev in conv.send(prompt, ctx=ctx, images=images or None):
                    f = to_rpc_frame(ev)
                    if f is not None:
                        await out_queue.put(f)
            except Exception as e:  # noqa: BLE001
                await out_queue.put({
                    "event": "error",
                    "data": {"code": "SEND_FAILED", "message": str(e)},
                })
            finally:
                await out_queue.put(None)  # sentinel:producer done

        prod_task = asyncio.create_task(_producer())
        try:
            while True:
                frame = await out_queue.get()
                if frame is None:
                    break
                yield frame
        finally:
            # 等 producer 收尾(若 caller 提前中斷,giveup 也 OK)
            if not prod_task.done():
                prod_task.cancel()
                try:
                    await prod_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            # Ask 模式中途斷線 → 把 pending future 全 deny,避免懸吊
            for fut in list(self._approvals.values()):
                if not fut.done():
                    fut.set_result(PermissionResult(
                        decision=PermissionDecision.DENY,
                        reason="conversation interrupted before approval",
                    ))
            self._approvals.clear()
            # AskUserQuestion pending 全 resolve 空 dict(tool 會回 "timed out")
            for fut in list(self._ask_pending.values()):
                if not fut.done():
                    fut.set_result({})
            self._ask_pending.clear()
            self._aborts.pop(sid, None)
            # Persist new messages(只 append 這 turn 增加的)
            new_msgs = conv.state_messages[before_count:]
            if new_msgs:
                try:
                    await storage.append_messages(engine, sid, new_msgs)
                except Exception:  # noqa: BLE001
                    # Persistence 失敗不該炸 sidecar — 之後重 send 還是會嘗試
                    pass

    def _build_can_use_tool(
        self,
        sid: str,
        out_queue: asyncio.Queue[dict[str, Any] | None],
        workspace_dir: "Path | None",
    ) -> Any:
        """組 can_use_tool callback。決策順序:

        1. policy deny match → DENY(全 mode 適用,即 Act 也擋)
        2. policy allow match → ALLOW(直接放行,不顯 banner)
        3. AskUserQuestion → ALLOW(自身就是問 user)
        4. session mode == 'ask' → 推 banner 等 approval
        5. session mode == 'act' → ALLOW

        Live:mode 跟 policy 都每次 invocation reload,中途切 Ask/Act 或加
        「永遠允許」rule 立刻生效,不必等下個 turn。
        """
        AUTO_ALLOW_TOOLS = {"AskUserQuestion"}

        async def _gate(tool: Any, tool_input: dict[str, Any], ctx: AgentContext) -> PermissionResult:  # noqa: ARG001
            tool_name = getattr(tool, "name", type(tool).__name__)
            # ① Policy deny / allow — 每次 reload 拿最新 rule
            policy = perm_mod.load_policy(workspace_dir)
            pdec = perm_mod.decide(policy, tool_name, tool_input)
            if pdec == "deny":
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason="denied by permission policy",
                )
            if pdec == "allow":
                return PermissionResult(decision=PermissionDecision.ALLOW)
            # ② Mode-based
            mode = self._session_modes.get(sid, "act")
            if mode != "ask":
                return PermissionResult(decision=PermissionDecision.ALLOW)
            if tool_name in AUTO_ALLOW_TOOLS:
                return PermissionResult(decision=PermissionDecision.ALLOW)
            tool_use_id = current_tool_use_id.get()
            if not tool_use_id:
                # 沒拿到 id 就不擋 — 保守起見走 allow,避免卡 loop
                return PermissionResult(decision=PermissionDecision.ALLOW)
            loop = asyncio.get_running_loop()
            future: asyncio.Future[PermissionResult] = loop.create_future()
            self._approvals[tool_use_id] = future
            await out_queue.put({
                "event": "tool_approval_request",
                "data": {
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "input": dict(tool_input),
                },
            })
            try:
                return await future
            finally:
                self._approvals.pop(tool_use_id, None)

        return _gate

    def _build_mode_aware_asker(
        self,
        sid: str,
        out_queue: asyncio.Queue[dict[str, Any] | None],
    ) -> Any:
        """Mode-dispatch asker callback。每次 invocation 讀 _session_modes 決定:

        - Ask 模式 → 推 ask_user_question frame、await renderer reply
        - Act 模式 → auto-decide,直接回 LLM 一個 hint 訊息叫它自己拿主意,
                    不打擾 user(對齊「放手讓我做」語意)

        Mode 切換不需要改 tool object / tools array,cache 不被破壞。
        """

        async def asker(questions: list[dict[str, Any]]) -> dict[str, str]:
            mode = self._session_modes.get(sid, "act")
            if mode != "ask":
                # Act 模式:auto-decide 回 hint,讓 LLM 看到「Act mode active,
                # 自己決定」訊息後不再嘗試問 user
                return {
                    str(q.get("question", "")): (
                        "[Act mode is active — please pick the most reasonable "
                        "default and proceed; do not ask the user. Continue "
                        "the task autonomously.]"
                    )
                    for q in questions
                }
            # Ask 模式:正常推 frame、await reply
            return await self._real_asker(out_queue, questions)

        return asker

    async def _real_asker(
        self,
        out_queue: asyncio.Queue[dict[str, Any] | None],
        questions: list[dict[str, Any]],
    ) -> dict[str, str]:
        """實際把問題推到 renderer 並等回應。從 _build_mode_aware_asker 內部呼叫。"""
        from uuid import uuid4

        request_id = uuid4().hex[:16]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, str]] = loop.create_future()
        self._ask_pending[request_id] = future
        await out_queue.put({
            "event": "ask_user_question",
            "data": {
                "request_id": request_id,
                "questions": questions,
            },
        })
        try:
            return await asyncio.wait_for(future, timeout=300.0)
        except TimeoutError:
            return {}
        finally:
            self._ask_pending.pop(request_id, None)

    async def stt_status(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """回前端 STT catalog(provider × model)+ per-provider API key 是否設。

        Catalog 來自 orion-model/stt_models.json,sidecar / chat-api / CLI 同源,
        前端不必硬編 model 清單。
        """
        import os

        from orion_model.stt_catalog import list_stt_catalog

        catalog = list_stt_catalog()
        env_map = {
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_STT_API_KEY",
        }
        providers = catalog.get("providers", [])
        if isinstance(providers, list):
            for p in providers:
                if not isinstance(p, dict):
                    continue
                env_name = env_map.get(p.get("id", ""))
                p["api_key_configured"] = bool(env_name and os.environ.get(env_name))
        yield {
            "event": "stt_status",
            "data": catalog,
            "final": True,
        }

    async def permissions_get(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """讀單一 scope 的 policy。

        params: { scope: 'global' | 'project', workspace_dir?: str }
        回:    { scope, allow: [...], deny: [...] }
        """
        from pathlib import Path as _P

        scope = params.get("scope")
        if scope not in ("global", "project"):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "scope must be 'global' | 'project'"},
                "final": True,
            }
            return
        ws_raw = params.get("workspace_dir")
        ws = _P(ws_raw) if isinstance(ws_raw, str) and ws_raw else None
        try:
            pol = perm_mod.load_scope(scope, ws)
        except Exception as e:  # noqa: BLE001
            yield {
                "event": "error",
                "data": {"code": "LOAD_FAILED", "message": str(e)},
                "final": True,
            }
            return
        yield {
            "event": "permissions",
            "data": {"scope": scope, "allow": pol.allow, "deny": pol.deny},
            "final": True,
        }

    async def permissions_set(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """覆寫單一 scope 的 policy。

        params: { scope, allow: [...], deny: [...], workspace_dir? }
        """
        from pathlib import Path as _P

        scope = params.get("scope")
        if scope not in ("global", "project"):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "scope must be 'global' | 'project'"},
                "final": True,
            }
            return
        allow_raw = params.get("allow")
        deny_raw = params.get("deny")
        allow = [s for s in allow_raw if isinstance(s, str)] if isinstance(allow_raw, list) else []
        deny = [s for s in deny_raw if isinstance(s, str)] if isinstance(deny_raw, list) else []
        ws_raw = params.get("workspace_dir")
        ws = _P(ws_raw) if isinstance(ws_raw, str) and ws_raw else None
        try:
            perm_mod.save_policy(perm_mod.Policy(allow=allow, deny=deny), scope=scope, workspace_dir=ws)
        except Exception as e:  # noqa: BLE001
            yield {
                "event": "error",
                "data": {"code": "SAVE_FAILED", "message": str(e)},
                "final": True,
            }
            return
        yield {
            "event": "permissions_saved",
            "data": {"scope": scope},
            "final": True,
        }

    async def conversation_stats(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """回 session 的 usage / cost / context-window stats。

        - cumulative:整個 session 累積到現在
        - last_turn:上一次 LLM 回覆的用量(讓 UI 顯「本次對話」)
        - cost_usd:用 orion_model.pricing × tokens 算 USD
        - context_used / context_max:上次 send 看到的 prompt size vs model 上限
        - cache_hit_rate:cache_read / (cache_read + input)
        """
        from orion_model.catalog import get_max_context_tokens
        from orion_model.pricing import get_pricing

        sid = params.get("session_id")
        if not isinstance(sid, str) or not sid:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
                "final": True,
            }
            return
        conv = self._conversations.get(sid)
        if conv is None:
            # Session 沒在 memory 但 DB 可能有 → 嘗試 resume(只為了拿 provider/model)
            engine = await self.ensure_engine()
            conv = await self._resume_from_db(sid, engine)
            if conv is None:
                yield {
                    "event": "error",
                    "data": {"code": "UNKNOWN_SESSION", "message": f"session {sid!r} not found"},
                    "final": True,
                }
                return
            self._conversations[sid] = conv

        s = conv.stats
        provider = conv.provider.name
        model = conv.provider.model

        # Pricing(USD per 1M tokens)
        pricing = get_pricing(provider, model)
        input_price = pricing.get("input", 0.0)
        output_price = pricing.get("output", 0.0)
        cache_read_price = pricing.get("cache_read", input_price)  # fallback to input
        cache_creation_price = pricing.get("cache_creation", input_price)

        def _cost(input_t: int, output_t: int, c_read: int, c_creation: int) -> float:
            return round(
                (
                    input_t * input_price
                    + output_t * output_price
                    + c_read * cache_read_price
                    + c_creation * cache_creation_price
                )
                / 1_000_000,
                6,
            )

        cumulative_cost = _cost(
            s.input_tokens, s.output_tokens, s.cache_read_tokens, s.cache_creation_tokens
        )
        last_cost = _cost(
            s.last_input_tokens,
            s.last_output_tokens,
            s.last_cache_read_tokens,
            s.last_cache_creation_tokens,
        )

        # Context window 用量 = 上次送 LLM 的 prompt size(input + cache_read)
        context_used = s.last_input_tokens + s.last_cache_read_tokens
        context_max = get_max_context_tokens(provider, model) or 0

        # Cache hit rate:cache_read 佔整個 prompt(read + 寫入 + 未命中)的比例。
        # 把 cache_creation 也算成「miss」— 第一次寫入時還沒享受到 cache,所以
        # cache_read / (cache_read + input + cache_creation) 更精準反映「省到錢」的占比。
        denom = s.cache_read_tokens + s.input_tokens + s.cache_creation_tokens
        cache_hit_rate = (s.cache_read_tokens / denom) if denom > 0 else 0.0

        yield {
            "event": "stats",
            "data": {
                "session_id": sid,
                "provider": provider,
                "model": model,
                "turns": s.turns,
                "tool_calls": s.tool_calls,
                "tool_errors": s.tool_errors,
                "cumulative": {
                    "input_tokens": s.input_tokens,
                    "output_tokens": s.output_tokens,
                    "cache_read_tokens": s.cache_read_tokens,
                    "cache_creation_tokens": s.cache_creation_tokens,
                    "reasoning_tokens": s.reasoning_tokens,
                    "cost_usd": cumulative_cost,
                },
                "last_turn": {
                    "input_tokens": s.last_input_tokens,
                    "output_tokens": s.last_output_tokens,
                    "cache_read_tokens": s.last_cache_read_tokens,
                    "cache_creation_tokens": s.last_cache_creation_tokens,
                    "reasoning_tokens": s.last_reasoning_tokens,
                    "cost_usd": last_cost,
                },
                "context_used": context_used,
                "context_max": context_max,
                "cache_hit_rate": round(cache_hit_rate, 4),
            },
            "final": True,
        }

    async def conversation_context_breakdown(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """/context — 算當前 context window 各 category 的 token 佔比。

        全 sidecar 端本機計算,不送 LLM。Token 估算用 char // 4(跟 compact 同一套標準)。

        Categories:
          - System prompt:fetch_system_prompt_parts + build_system_prompt_list 重 build
          - System tools:builtin tools 各自 JSON schema 字符 // 4
          - MCP tools:active MCP tools 各自 JSON schema(細項回 per-server)
          - Skills:bundled / system / user / project skills 的 name+description
          - Messages:estimate_token_count(state_messages)
          - Autocompact buffer:max_context * (1 - threshold)
          - Free space:max - 上述總和
        """
        import json as _json

        from orion_sdk.compact.auto import estimate_token_count
        from orion_sdk.prompt.assembler import (
            build_system_prompt_list,
            fetch_system_prompt_parts,
        )

        sid = params.get("session_id")
        if not isinstance(sid, str) or not sid:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
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

        # ─── 1) System prompt ────────────────────────────────────────────
        cwd = await self._resolve_session_cwd(sid, engine)
        try:
            parts = await fetch_system_prompt_parts(
                cwd=cwd if conv.include_workspace_context else None,
                user_id=conv.user_id,
                conversation_messages=conv.state_messages,
                provider=conv.provider if conv.memory_enabled else None,
                mcp_manager=conv.mcp_manager,
                custom_instructions_user=conv.custom_instructions_user,
                custom_instructions_conversation=conv.custom_instructions_conversation,
                output_style=conv.output_style,
                include_workspace_context=conv.include_workspace_context,
                include_env_info=conv.include_env_info,
            )
            system_segments = build_system_prompt_list(parts)
        except Exception:  # noqa: BLE001 — fallback,不擋整個 RPC
            system_segments = [conv.system_prompt] if conv.system_prompt else []
        system_text = "\n\n".join(s for s in system_segments if s)
        if conv.system_prompt and not any(conv.system_prompt in s for s in system_segments):
            system_text = conv.system_prompt + "\n\n" + system_text
        system_tokens = len(system_text) // 4

        # ─── 2/3) Tools — 區分 builtin vs MCP ────────────────────────────
        # MCP tools 名字慣例 "mcp__<server>__<tool>";其他都是 builtin
        builtin_tools_tokens = 0
        mcp_tools_detail: list[dict[str, Any]] = []
        for tool in conv.tools:
            tname = getattr(tool, "name", None)
            if not isinstance(tname, str):
                continue
            try:
                schema = tool.input_schema.model_json_schema()
            except Exception:  # noqa: BLE001
                schema = {}
            schema_dict = {
                "name": tname,
                "description": getattr(tool, "description", "") or "",
                "input_schema": schema,
            }
            tokens = len(_json.dumps(schema_dict, ensure_ascii=False)) // 4
            if tname.startswith("mcp__"):
                bits = tname.split("__", 2)
                server = bits[1] if len(bits) >= 3 else "unknown"
                mcp_tools_detail.append(
                    {"name": tname, "server": server, "tokens": tokens}
                )
            else:
                builtin_tools_tokens += tokens
        mcp_tools_detail.sort(key=lambda d: (d["server"], d["name"]))
        mcp_tools_tokens = sum(d["tokens"] for d in mcp_tools_detail)

        # ─── 4) Skills ──────────────────────────────────────────────────
        skills_detail: list[dict[str, Any]] = []
        try:
            from orion_sdk.skills.loader import (
                _bundled_skills,
                _system_skills_dir,
                load_skills_dir,
            )

            from orion_cowork_sidecar.skill_handlers import (
                _label_source,
                _user_skills_dir,
            )

            by_name: dict[str, Any] = {}
            # Project skills(優先 — 若 session 有 workspace 跟 project)
            ext = await storage.get_session_ext(engine, sid)
            if ext.get("project_id"):
                proj = await storage.get_project(engine, ext["project_id"])
                if proj is not None and proj.workspace_dir:
                    pdir = Path(proj.workspace_dir) / ".orion-cowork" / "skills"
                    if pdir.is_dir():
                        for sk in load_skills_dir(pdir):
                            by_name[sk.name] = sk
            else:
                for sk in _bundled_skills():
                    by_name[sk.name] = sk
                for sk in load_skills_dir(_system_skills_dir()):
                    by_name[sk.name] = sk
                for sk in load_skills_dir(_user_skills_dir()):
                    by_name[sk.name] = sk
            for sk in sorted(by_name.values(), key=lambda s: s.name.lower()):
                text = (sk.name or "") + (sk.description or "")
                source = _label_source(sk.source_path) if sk.source_path else "unknown"
                skills_detail.append(
                    {"name": sk.name, "source": source, "tokens": len(text) // 4}
                )
        except Exception:  # noqa: BLE001
            pass
        skills_tokens = sum(d["tokens"] for d in skills_detail)

        # ─── 5) Messages ────────────────────────────────────────────────
        messages_tokens = estimate_token_count(conv.state_messages)

        # ─── 6/7) Buffer + Free ─────────────────────────────────────────
        max_context = conv.provider.capabilities.max_context_tokens
        threshold = conv.auto_compact_threshold if conv.auto_compact_threshold else 0.8
        autocompact_buffer_tokens = int(max_context * (1.0 - threshold))
        used = (
            system_tokens
            + builtin_tools_tokens
            + mcp_tools_tokens
            + skills_tokens
            + messages_tokens
        )
        free_space = max(0, max_context - used - autocompact_buffer_tokens)

        yield {
            "event": "context_breakdown",
            "data": {
                "session_id": sid,
                "provider": conv.provider.name,
                "model": conv.provider.model,
                "max_context_tokens": max_context,
                "total_used_tokens": used,
                "categories": [
                    {"name": "System prompt", "tokens": system_tokens},
                    {"name": "System tools", "tokens": builtin_tools_tokens},
                    {"name": "MCP tools", "tokens": mcp_tools_tokens},
                    {"name": "Skills", "tokens": skills_tokens},
                    {"name": "Messages", "tokens": messages_tokens},
                    {"name": "Free space", "tokens": free_space},
                    {"name": "Autocompact buffer", "tokens": autocompact_buffer_tokens},
                ],
                "mcp_tools_detail": mcp_tools_detail,
                "skills_detail": skills_detail,
            },
            "final": True,
        }

    async def conversation_compact(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """手動觸發對話壓縮 — 把 state_messages 前段摘要成單一 TombstoneBlock。

        force=True(預設):跳過 threshold,直接壓。
        force=False:走 SDK auto threshold(用 conv.auto_compact_threshold)。

        事件序列:compact_started → (LLM 摘要 ~3~5s) → compact_complete
        DB 端同步:替換成 [tombstone, ...保留段]。
        """
        sid = params.get("session_id")
        force = bool(params.get("force", True))
        if not isinstance(sid, str) or not sid:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
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

        # 把 UI locale 寫進 conv,SDK 摘要會用該語系生成
        locale_raw = params.get("locale")
        if isinstance(locale_raw, str) and locale_raw:
            conv.compact_summary_locale = locale_raw
        # Summary model override:同 conversation_send 邏輯
        _apply_summary_provider(conv, params)

        yield {"event": "compact_started", "data": {"session_id": sid}}

        pre_compact_state_count = len(conv.state_messages)
        try:
            result = await conv.compact(force=force)
        except Exception as e:  # noqa: BLE001
            yield {
                "event": "error",
                "data": {"code": "COMPACT_FAILED", "message": str(e)},
                "final": True,
            }
            return

        if not result.was_compacted:
            yield {
                "event": "compact_complete",
                "data": {
                    "summary": "",
                    "before_tokens": 0,
                    "after_tokens": result.after_tokens,
                    "compacted_count": 0,
                    "skipped": True,
                    "auto": False,
                },
                "final": True,
            }
            return

        # DB soft-delete + append tombstone(同 auto 路徑)
        compacted_count = pre_compact_state_count - (result.kept_message_count - 1)
        tombstone_msg = conv.state_messages[0]
        try:
            await storage.record_compaction(
                engine, sid,
                compacted_count=compacted_count,
                tombstone_msg=tombstone_msg,
            )
        except Exception as e:  # noqa: BLE001
            import sys
            print(f"[sidecar] compact DB sync failed: {e}", file=sys.stderr, flush=True)

        yield {
            "event": "compact_complete",
            "data": {
                "summary": result.summary,
                "before_tokens": result.before_tokens,
                "after_tokens": result.after_tokens,
                "compacted_count": compacted_count,
                "skipped": False,
                "auto": False,
            },
            "final": True,
        }

    async def conversation_set_permission_mode(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """中途切 Ask / Act 模式。切到 'act' 時 auto-resolve 所有 pending
        approvals(allow)和 ask futures(空回答),讓 in-flight turn 立刻
        不再被卡住。
        """
        sid = params.get("session_id")
        mode = params.get("mode")
        if not isinstance(sid, str) or mode not in ("ask", "act"):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id + mode required"},
                "final": True,
            }
            return
        self._session_modes[sid] = mode
        if mode == "act":
            # 切到放手 → 把目前等 user 決定的 approval 一律放行;ask question
            # 空回答(LLM 看到 "user didn't respond" 自己繼續判斷)
            for fut in list(self._approvals.values()):
                if not fut.done():
                    fut.set_result(PermissionResult(
                        decision=PermissionDecision.ALLOW,
                        reason="permission_mode switched to act",
                    ))
            self._approvals.clear()
            for fut in list(self._ask_pending.values()):
                if not fut.done():
                    fut.set_result({})
            self._ask_pending.clear()
        yield {
            "event": "permission_mode_set",
            "data": {"session_id": sid, "mode": mode},
            "final": True,
        }

    async def conversation_ask_user_reply(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Renderer 把 user 答案 post 回來。answers: {question_text -> chosen_label}。"""
        request_id = params.get("request_id")
        answers = params.get("answers")
        if not isinstance(request_id, str) or not isinstance(answers, dict):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "request_id + answers required"},
                "final": True,
            }
            return
        fut = self._ask_pending.get(request_id)
        if fut is None or fut.done():
            yield {
                "event": "ask_ack",
                "data": {"request_id": request_id, "status": "stale"},
                "final": True,
            }
            return
        # 強制 cast 成 dict[str, str](renderer 已負責序列化)
        normalized = {str(k): str(v) for k, v in answers.items()}
        fut.set_result(normalized)
        yield {
            "event": "ask_ack",
            "data": {"request_id": request_id, "status": "applied"},
            "final": True,
        }

    async def conversation_tool_approval(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Renderer 回 tool approval 決定(decision='allow' | 'deny')。"""
        tool_use_id = params.get("tool_use_id")
        decision = params.get("decision")
        reason = params.get("reason") or ""
        if not isinstance(tool_use_id, str) or decision not in ("allow", "deny"):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "tool_use_id + decision required"},
                "final": True,
            }
            return
        fut = self._approvals.get(tool_use_id)
        if fut is None or fut.done():
            yield {
                "event": "approval_ack",
                "data": {"tool_use_id": tool_use_id, "status": "stale"},
                "final": True,
            }
            return
        fut.set_result(PermissionResult(
            decision=PermissionDecision(decision),
            reason=reason or ("user denied" if decision == "deny" else ""),
        ))
        yield {
            "event": "approval_ack",
            "data": {"tool_use_id": tool_use_id, "status": "applied"},
            "final": True,
        }

    async def _sync_mcp_for_session(
        self, sid: str, engine: AsyncEngine
    ) -> None:
        """B2:依 chat 的 project workspace 決定要不要 reload MCP manager。

        只在 active extra(project layer)跟 chat 需要的 extra **不同**時 reload —
        避免每 turn 都 kill 重連。
        """
        from pathlib import Path
        from orion_cowork_sidecar.mcp_integration import load_project_mcp_configs

        ext = await storage.get_session_ext(engine, sid)
        wanted: dict[str, Any] = {}
        if ext["project_id"]:
            proj = await storage.get_project(engine, ext["project_id"])
            if proj is not None and proj.workspace_dir:
                wanted = load_project_mcp_configs(Path(proj.workspace_dir))
        # 比對:active extra 跟 wanted 一不一樣(by name set + by config dump)
        current_names = set(self._mcp.active_extra.keys())
        wanted_names = set(wanted.keys())
        if current_names == wanted_names and not wanted:
            return  # 兩邊都 empty,無事可做
        if current_names == wanted_names:
            # 同 names,內容可能不同 — 比 dump
            cur_dump = {k: v.model_dump() for k, v in self._mcp.active_extra.items()}
            new_dump = {k: v.model_dump() for k, v in wanted.items()}
            if cur_dump == new_dump:
                return
        # 不同 → reload
        await self._mcp.reload(extra_configs=wanted)
        self._mcp_started = True

    async def _resolve_session_cwd(
        self, sid: str, engine: AsyncEngine
    ) -> "Path | None":
        """Session 的 effective workspace_dir。

        優先序:session-level override > project > app-level default(prefs)→ None
        """
        from pathlib import Path
        ext = await storage.get_session_ext(engine, sid)
        ws = ext["workspace_dir"]
        if not ws and ext["project_id"]:
            proj = await storage.get_project(engine, ext["project_id"])
            if proj is not None:
                ws = proj.workspace_dir
        if not ws:
            ws = await storage.get_pref(engine, "default_workspace_dir")
        return Path(ws) if ws else None

    async def prefs_get_all(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        engine = await self.ensure_engine()
        prefs = await storage.list_prefs(engine)
        yield {"event": "prefs", "data": {"prefs": prefs}, "final": True}

    async def prefs_set(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """params: {key, value}。value=None 刪除該 key。"""
        key = params.get("key")
        value = params.get("value")
        if not isinstance(key, str) or not key:
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        if value is not None and not isinstance(value, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        await storage.set_pref(engine, key, value)
        # default_workspace_dir / user_instructions 變更 → 既有 cached conv
        # 失效(下次 send 用新值,system_prompt / cwd 才會跟著刷新)
        if key in ("default_workspace_dir", "user_instructions"):
            self._conversations.clear()
        yield {"event": "prefs_set", "data": {"key": key}, "final": True}

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
        from pathlib import Path
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
        # session > project > app-level default(prefs)→ None
        # project-level custom_instructions 注入 system_prompt 後

        effective_workspace: str | None = workspace_dir
        project_custom_instructions: str | None = None
        if project_id:
            proj = await storage.get_project(engine, project_id)
            if proj is not None:
                if not effective_workspace and proj.workspace_dir:
                    effective_workspace = proj.workspace_dir
                project_custom_instructions = proj.custom_instructions
        # B4:project instructions file 優先 — user 直接編 `<ws>/.orion-cowork/
        # instructions.md` 不用過 RPC,read 時拿 file content。
        if effective_workspace:
            from pathlib import Path as _Path
            inst_file = _Path(effective_workspace) / ".orion-cowork" / "instructions.md"
            if inst_file.is_file():
                try:
                    project_custom_instructions = inst_file.read_text(encoding="utf-8")
                except OSError:
                    pass
        if not effective_workspace:
            effective_workspace = await storage.get_pref(
                engine, "default_workspace_dir",
            )

        # Context-aware:project chat 內 prompt 內容指向 project paths,
        # 個人 chat 指向 user-level paths — 避免 LLM 在 project 內把檔案下
        # 到個人庫(反之亦然)。
        system_prompt = _COWORK_PROMPT_BASE + _paths_section(
            workspace_dir=effective_workspace,
            in_project=bool(project_id),
        )
        # User-level instructions(prefs)— 跨 project 跨對話一律生效,
        # 例如「always answer in zh-TW」、「I'm a senior engineer, skip basics」
        user_instructions = await storage.get_pref(engine, "user_instructions")
        if user_instructions and user_instructions.strip():
            system_prompt += "\n\n# Your instructions for Orion\n\n" + user_instructions.strip()
        if project_custom_instructions:
            system_prompt += "\n\n# Project instructions\n\n" + project_custom_instructions

        include_ws = bool(effective_workspace)
        # Project chat → auto-extract 寫 <workspace>/.orion-cowork/memory/
        # 沒 project → 寫 user-level(SDK default)
        memory_override: Path | None = None
        if project_id and effective_workspace:
            memory_override = Path(effective_workspace) / ".orion-cowork" / "memory"
            memory_override.mkdir(parents=True, exist_ok=True)

        conv_kwargs: dict[str, Any] = dict(
            provider=llm,
            tools=tools,
            persistence_enabled=False,
            user_id=storage.LOCAL_USER_ID,
            memory_enabled=True,
            auto_extract_memories=True,
            memory_dir_override=memory_override,
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
        # LLM 看的版本跳過 compacted_out=true 的舊訊息(只看 tombstone + 之後)。
        # UI 端走 load_raw_messages 拿全量,自己按 metadata 標 compacted 淡化。
        state_messages = await storage.load_active_messages_for_llm(engine, sid)
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
        # 喚醒任何 pending approval / AskUserQuestion futures — 否則它們繼續
        # await 沒有人會 resolve,conv.send 內部就卡住,abort_event 永遠
        # 沒機會被檢查到。Approval 視為 deny、AskUser 視為空回答。
        for fut in list(self._approvals.values()):
            if not fut.done():
                fut.set_result(PermissionResult(
                    decision=PermissionDecision.DENY,
                    reason="aborted by user",
                ))
        self._approvals.clear()
        for fut in list(self._ask_pending.values()):
            if not fut.done():
                fut.set_result({})
        self._ask_pending.clear()
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
        # Resolved cwd 走完整 fallback 鏈(session > project > app default),給
        # /export 等需要實際路徑的 caller 用
        resolved = await self._resolve_session_cwd(sid, engine)
        yield {
            "event": "session_ext",
            "data": {
                "session_id": sid,
                "workspace_dir": ext["workspace_dir"],
                "project_id": ext["project_id"],
                "resolved_cwd": str(resolved) if resolved else None,
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
        workspace_dir = params.get("workspace_dir")
        if not isinstance(name, str) or not name.strip():
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "name required"}, "final": True}
            return
        if not isinstance(workspace_dir, str) or not workspace_dir.strip():
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "workspace_dir required (B0: project must have a workspace)"},
                   "final": True}
            return
        engine = await self.ensure_engine()
        proj = await storage.create_project(
            engine,
            name=name.strip(),
            workspace_dir=workspace_dir.strip(),
            description=params.get("description") or None,
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
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """讀 mcp.json 全部 server raw config。有 project_id 走 project mcp.json。"""
        from pathlib import Path
        from orion_cowork_sidecar.mcp_integration import (
            cowork_mcp_config_path,
            read_mcp_config_raw,
        )
        project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
        target: Path
        if project_id:
            engine = await self.ensure_engine()
            proj = await storage.get_project(engine, project_id)
            if proj is None or not proj.workspace_dir:
                yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
                return
            target = Path(proj.workspace_dir) / ".orion-cowork" / "mcp.json"
        else:
            target = cowork_mcp_config_path()
        servers = read_mcp_config_raw(target)
        yield {
            "event": "mcp_config_list",
            "data": {
                "config_path": str(target),
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

        from pathlib import Path
        project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
        target: Path | None = None
        if project_id:
            engine = await self.ensure_engine()
            proj = await storage.get_project(engine, project_id)
            if proj is None or not proj.workspace_dir:
                yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
                return
            target = Path(proj.workspace_dir) / ".orion-cowork" / "mcp.json"
        servers = read_mcp_config_raw(target)
        if isinstance(rename_from, str) and rename_from and rename_from != name:
            servers.pop(rename_from, None)
        servers[name.strip()] = config
        write_mcp_config_raw(servers, target)
        # global 變更 reload manager;project 變更靠下次 send 時 _sync_mcp_for_session
        if not project_id:
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
        from pathlib import Path
        project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None
        target: Path | None = None
        if project_id:
            engine = await self.ensure_engine()
            proj = await storage.get_project(engine, project_id)
            if proj is None or not proj.workspace_dir:
                yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
                return
            target = Path(proj.workspace_dir) / ".orion-cowork" / "mcp.json"
        servers = read_mcp_config_raw(target)
        if name not in servers:
            yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
            return
        servers.pop(name)
        write_mcp_config_raw(servers, target)
        if not project_id:
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

    async def conversation_truncate(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """從指定 message_index(含)起 truncate 對話 — edit / delete 都走這。

        Params:
          session_id: 必填
          message_index: raw row index(對齊 load_raw_messages 順序);
                         renderer 的 message.messageIndex
          resend_text (optional): 給了就 truncate 後重跑 send(=edit & resend)
          resend_images (optional): 同上,attachments
          permission_mode (optional): resend 時帶的模式

        Pre-conditions:
          - message_index 對應的 row 不能是 compacted_out=true(renderer 端 UI
            應禁止;這裡也防一層)

        Cache impact:
          - state_messages 從該 idx 起被砍,prefix 改變 → BP3 / BP4 cache 全失效
          - BP1(tools+system_E0)、BP2(system_E1)不變
        """
        sid = params.get("session_id")
        msg_idx = params.get("message_index")
        if sid is None or not isinstance(msg_idx, int):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id + message_index required"},
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
        # DB layer truncate(只刪 raw_index 以後 row)
        try:
            removed = await storage.truncate_messages_from(
                engine, sid, raw_index=msg_idx,
            )
        except Exception as e:  # noqa: BLE001
            yield {
                "event": "error",
                "data": {"code": "TRUNCATE_FAILED", "message": str(e)},
                "final": True,
            }
            return

        # 同步 in-memory conv:用 active loader 重建 state_messages
        conv = self._conversations.get(sid)
        if conv is not None:
            conv.state_messages = await storage.load_active_messages_for_llm(engine, sid)

        # 沒 resend_text → 純 delete,emit ack 給 renderer reload UI
        resend_text = params.get("resend_text")
        if not isinstance(resend_text, str) or not resend_text.strip():
            yield {
                "event": "truncate_complete",
                "data": {"session_id": sid, "removed": removed, "resend": False},
                "final": True,
            }
            return

        # 有 resend_text → 走 send 流程
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

        # 重組 images(沿用 conversation_send 邏輯)
        from orion_model.types import ImageBlock
        images: list[Any] = []
        raw_atts = params.get("resend_images") or []
        if isinstance(raw_atts, list):
            for a in raw_atts:
                if not isinstance(a, dict):
                    continue
                media_type = a.get("media_type") or "image/png"
                data = a.get("data")
                if not isinstance(data, str) or not data:
                    continue
                try:
                    images.append(ImageBlock(media_type=media_type, data=data))
                except Exception:  # noqa: BLE001
                    continue

        # 先發 truncate_complete 讓 UI 清舊訊息,再 send 串流新 turn
        yield {
            "event": "truncate_complete",
            "data": {"session_id": sid, "removed": removed, "resend": True},
        }

        permission_mode = params.get("permission_mode", "act")
        self._session_modes[sid] = permission_mode

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
            async for ev in conv.send(resend_text, ctx=ctx, images=images or None):
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

        # 找最後一個「真 user prompt」message — 排除 tool_result message
        # (Anthropic 內 tool_result 屬於 role=user 的 content,直接 by role 過濾
        # 會切錯點,留下 dangling tool_use → OpenAI 拒「No tool output found」)
        from orion_model.types import ToolResultBlock

        def _is_user_prompt(m: Any) -> bool:
            if m.role != "user":
                return False
            c = m.content
            if isinstance(c, str):
                return True
            if isinstance(c, list):
                return not any(isinstance(b, ToolResultBlock) for b in c)
            return False

        msgs = conv.state_messages
        last_user_idx = -1
        for i in range(len(msgs) - 1, -1, -1):
            if _is_user_prompt(msgs[i]):
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


def _apply_summary_provider(conv: Conversation, params: dict[str, Any]) -> None:
    """從 RPC params 讀 summary_provider / summary_model,build provider 注入 conv。

    沒給 / 建失敗 → 不動 conv.compact_summary_provider(SDK 自動 fallback 到
    conv.provider,跟 chat 同一個 model)。失敗 silent ignore — 摘要還是會跑,
    只是用貴的 model。
    """
    sp_name = params.get("summary_provider")
    sp_model = params.get("summary_model")
    if not isinstance(sp_name, str) or not sp_name:
        return
    if not isinstance(sp_model, str) or not sp_model:
        return
    try:
        conv.compact_summary_provider = get_provider(sp_name, sp_model)
    except Exception as e:  # noqa: BLE001
        import sys
        print(
            f"[sidecar] summary provider build failed ({sp_name}/{sp_model}): {e}",
            file=sys.stderr, flush=True,
        )


def _is_user_prompt_row(content_json: Any) -> bool:
    """role=user 但 content 不全 tool_result(亦即真的 user prompt)。"""
    if isinstance(content_json, str):
        return True
    if not isinstance(content_json, list):
        return False
    has_non_tool_result = False
    for b in content_json:
        if isinstance(b, dict) and b.get("type") != "tool_result":
            has_non_tool_result = True
            break
    return has_non_tool_result


def _row_is_tombstone(content_json: Any) -> bool:
    """偵測 row 是否是 compact 留下的 tombstone(role=user content=[TombstoneBlock])。"""
    if not isinstance(content_json, list) or len(content_json) != 1:
        return False
    b = content_json[0]
    return isinstance(b, dict) and b.get("type") == "tombstone"


def _to_ui_messages_from_raw(
    rows: "list[tuple[str, Any, Any]]",
) -> list[dict[str, Any]]:
    """Raw (role, content_json, metadata_json) → UI dict,不 hydrate image blob bytes。

    把連續 assistant + tool_result(role=user)合併成單一 UI assistant turn —
    跟 streaming 時 RightSidebar / ToolCallGroup 看到的形狀一致(整 turn 工具
    收進同一個 group),歷史對話 reload 後不會散成多個小 group。

    特別處理:
    - metadata_json.compacted_out=True 的 row → UI 加上 compacted=True 旗標,前端淡化
    - content 是單一 TombstoneBlock → 翻成 system kind=compact-summary card
    """
    # 第一 pass:tool_use_id → {text, is_error}
    result_map: dict[str, dict[str, Any]] = {}
    for _, content_json, _ in rows:
        if not isinstance(content_json, list):
            continue
        for b in content_json:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            tuid = b.get("tool_use_id")
            if not isinstance(tuid, str):
                continue
            content = b.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts: list[str] = []
                for inner in content:
                    if isinstance(inner, dict) and inner.get("type") == "text":
                        parts.append(str(inner.get("text", "")))
                text = "\n".join(parts)
            else:
                text = ""
            result_map[tuid] = {
                "text": text,
                "is_error": bool(b.get("is_error", False)),
            }

    out: list[dict[str, Any]] = []
    i = 0
    while i < len(rows):
        role, content_json, meta = rows[i]
        is_compacted = isinstance(meta, dict) and bool(meta.get("compacted_out"))

        # Tombstone row → 單獨 emit 一張 compact-summary card,然後跳過
        if _row_is_tombstone(content_json):
            tb = content_json[0]
            out.append({
                "role": "system",
                "text": str(tb.get("summary", "")),
                "attachments": [],
                "tool_calls": [],
                "blocks": [],
                "message_index": i,
                "kind": "compact-summary",
                "before_tokens": int(tb.get("original_token_count", 0) or 0),
            })
            i += 1
            continue

        # 純 user prompt → emit user message + 收 attachments(若有)
        if role == "user" and _is_user_prompt_row(content_json):
            text = ""
            attachments: list[dict[str, Any]] = []
            if isinstance(content_json, str):
                text = content_json
            elif isinstance(content_json, list):
                att_idx = 0
                for b in content_json:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        text += b.get("text", "")
                    elif b.get("type") == "image":
                        attachments.append({
                            "media_type": b.get("media_type") or "image/png",
                            "ref": {
                                "message_index": i,
                                "attachment_index": att_idx,
                            },
                        })
                        att_idx += 1
            if text or attachments:
                out.append({
                    "role": "user",
                    "text": text,
                    "attachments": attachments,
                    "tool_calls": [],
                    "blocks": [],
                    "message_index": i,
                    "compacted": is_compacted,
                })
            i += 1
            continue
        # 從這裡到下一個 user prompt / tombstone(或 EOF)合併成單一 assistant turn
        merged_text = ""
        merged_tool_calls: list[dict[str, Any]] = []
        merged_blocks: list[dict[str, Any]] = []
        merged_attachments: list[dict[str, Any]] = []
        tools_buffer: list[str] = []
        first_idx = i
        merged_compacted = is_compacted
        while i < len(rows):
            r2, cj2, meta2 = rows[i]
            if _row_is_tombstone(cj2):
                break
            if r2 == "user" and _is_user_prompt_row(cj2):
                break  # 進入下個 turn
            if r2 == "user" and _is_user_prompt_row(cj2):
                break  # 進入下個 turn
            if isinstance(cj2, list):
                for b in cj2:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get("type")
                    if btype == "text":
                        if tools_buffer:
                            merged_blocks.append({"type": "tools", "tool_use_ids": tools_buffer})
                            tools_buffer = []
                        t = b.get("text", "")
                        merged_text += t
                        if t:
                            merged_blocks.append({"type": "text", "text": t})
                    elif btype == "tool_use":
                        tuid = b.get("id") or ""
                        if isinstance(tuid, str) and tuid:
                            r = result_map.get(tuid, {"text": "", "is_error": False})
                            merged_tool_calls.append({
                                "tool_use_id": tuid,
                                "tool_name": b.get("name") or "",
                                "input": b.get("input") or {},
                                "status": "error" if r["is_error"] else "success",
                                "text": r["text"],
                            })
                            tools_buffer.append(tuid)
                    elif btype == "image":
                        # assistant message 通常不含 image,但 defensive 處理
                        merged_attachments.append({
                            "media_type": b.get("media_type") or "image/png",
                            "ref": {
                                "message_index": i,
                                "attachment_index": len(merged_attachments),
                            },
                        })
                    # tool_result block:已被 result_map 收;此處不重複處理
            elif isinstance(cj2, str):
                if tools_buffer:
                    merged_blocks.append({"type": "tools", "tool_use_ids": tools_buffer})
                    tools_buffer = []
                merged_text += cj2
                if cj2:
                    merged_blocks.append({"type": "text", "text": cj2})
            i += 1
        if tools_buffer:
            merged_blocks.append({"type": "tools", "tool_use_ids": tools_buffer})
        if merged_text or merged_tool_calls or merged_attachments:
            out.append({
                "role": "assistant",
                "text": merged_text,
                "attachments": merged_attachments,
                "tool_calls": merged_tool_calls,
                "blocks": merged_blocks,
                "message_index": first_idx,
                "compacted": merged_compacted,
            })

    # ─── Position-based 防呆 ──────────────────────────────────────────────
    # 任何在最後一張 compact-summary card 之前的 user / assistant message,
    # 一律標 compacted=True。萬一 metadata_json.compacted_out 沒寫好(舊資料
    # 或 update race),UI 仍能正確淡化 + 隱藏 edit/delete。
    last_summary_idx = -1
    for idx, msg in enumerate(out):
        if msg.get("kind") == "compact-summary":
            last_summary_idx = idx
    if last_summary_idx > 0:
        for idx in range(last_summary_idx):
            if out[idx].get("role") in ("user", "assistant"):
                out[idx]["compacted"] = True
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
