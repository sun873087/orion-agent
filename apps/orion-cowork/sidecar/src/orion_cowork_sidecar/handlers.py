"""RPC method handlers — 連 orion-sdk Conversation。

後:對話跨 app restart 保留(本機 SQLite)。
~/.orion/sessions/cowork.db 由 storage.py 管理。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Awaitable, Callable
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
from orion_sdk.plan_mode.state import (
    PlanModeState,
    PlanModeStatus,
    approve_and_exit,
    reject_and_exit,
)
from orion_sdk.services.feature_flags import load_feature_flags
from orion_sdk.tools.agent.agent_tool import AgentTool
from orion_sdk.tools.builtin_set import build_default_tool_set
from orion_sdk.tools.special.enter_plan_mode import EnterPlanModeTool
from orion_sdk.tools.special.exit_plan_mode import ExitPlanModeTool

from orion_cowork_sidecar import (
    backup_handlers,
    memory_handlers,
    permissions as perm_mod,
    role_handlers,
    schedule_handlers,
    skill_handlers,
    storage,
    stt_handlers,
    tts_handlers,
)
from orion_cowork_sidecar.desktop_tools import OpenPathTool, OpenUrlTool
from orion_cowork_sidecar.mcp_integration import CoworkMcpManager
from orion_cowork_sidecar.scheduler import SchedulerEngine
from orion_cowork_sidecar.streaming import to_rpc_frame

# 只讀 per-app .env(apps/orion-cowork/.env);不抓 project root .env。
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def _unwrap_exception(e: BaseException) -> BaseException:
    """asyncio.TaskGroup / anyio 把實際錯包成 ExceptionGroup;遞迴解到 leaf
    (只 unwrap 「單一 sub-exception」的情境,避免吞掉多重錯)。"""
    seen: set[int] = set()
    while True:
        if id(e) in seen:
            return e
        seen.add(id(e))
        # Python 3.11+ ExceptionGroup / BaseExceptionGroup
        subs = getattr(e, "exceptions", None)
        if isinstance(subs, (list, tuple)) and len(subs) == 1:
            e = subs[0]
            continue
        # 也順手解 __cause__ / __context__(API SDK 常用)
        cause = getattr(e, "__cause__", None)
        if cause is not None and not subs:
            e = cause
            continue
        return e


def _format_send_error(e: BaseException) -> tuple[str, str]:
    """把 SDK 例外轉成 user-friendly (code, message)。

    優先看 OpenAI / Anthropic SDK 的 specific class name + status_code,
    fallback 用 type name + str。輸出簡短能讓 user 看得懂的訊息,完整
    stack trace 走 stderr log,不要塞給 UI。
    """
    inner = _unwrap_exception(e)
    name = type(inner).__name__
    status = getattr(inner, "status_code", None)

    # Mapping by class name(不 import SDK 避免硬依賴 specific版本)
    if name == "AuthenticationError" or status == 401:
        return ("AUTH_FAILED",
                "API key 認證失敗 — 檢查 ORION_MODEL_PROXY_KEY 是否有效,"
                "或請 admin 在 proxy /admin/ui 重發一個 token")
    if name == "PermissionDeniedError" or status == 403:
        return ("PERMISSION_DENIED",
                "此 API key 已被 revoke 或無權使用 — 聯絡 admin 重發 token")
    if name == "RateLimitError" or status == 429:
        return ("RATE_LIMIT", "Provider 速率限制,請稍候再試")
    if status == 402:
        return ("BUDGET_EXCEEDED",
                "Budget 上限已達 — 請 admin 在 proxy /admin/ui 提升 cap")
    if name in ("APIConnectionError", "ConnectError", "ConnectTimeout"):
        return ("CONNECTION_FAILED",
                f"無法連到 proxy / upstream:{inner}。檢查 ORION_MODEL_PROXY_URL "
                "指對地方且 proxy 在跑")
    if status and status >= 500:
        return (f"UPSTREAM_{status}",
                f"上游 provider {status} 錯誤,通常稍候會自己好:{str(inner)[:200]}")
    if name == "APIStatusError" and status:
        return (f"HTTP_{status}", str(inner)[:300])

    # Fallback — 至少給 type + str,不要 dump ExceptionGroup 給 user 看
    msg = str(inner) or repr(inner)
    return (name, msg[:300])


def _walk_workspace(root: Path, skip_dirs: set[str]):
    """Sync generator yielding files under root, skipping common heavy dirs.

    Caller's outer function is async but this walk is sync and fast for
    typical workspaces。Return type annotation 省略避免 mypy 跟 ast 衝突。
    """
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        # In-place modify dirnames so os.walk skips matching subdirs
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue # 跳 dotfile(.DS_Store 等)
            yield Path(dirpath) / name


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
    "Local data lives under `~/.orion/` (shared with the CLI / chat-api hosts). "
    "Cowork's own sessions go to `~/.orion/sessions/cowork.db`; "
    "skills / memory / MCP config are shared so a skill you install via CLI shows "
    "up in Cowork and vice versa.\n"
    "\n"
    "When the user attaches images, describe or analyze them as requested. "
    "Do not refuse desktop actions on grounds of 'I can't control your computer' — "
    "you can, that's what the tools above are for. Just do what they asked, then "
    "report what you did.\n"
    "\n"
    "# Match effort to the request\n"
    "Calibrate how much you do to what was actually asked:\n"
    "- Pure conversational messages (greetings like 'hi', 'thanks', simple "
    " chit-chat, single factual questions you can answer from your own "
    " knowledge) — JUST REPLY. Do NOT call TodoWrite, AskUserQuestion, web "
    " search, or any other tool. Tools are for actual work.\n"
    "- Genuine multi-step tasks (2+ distinct actions like 'plan → write → "
    " run → verify', 'install dep → generate file → open it') — call "
    " `TodoWrite` FIRST with the full plan, then update items as you progress "
    " (pending → in_progress → completed). Skip TodoWrite for one-shot work.\n"
    "- Ambiguous requests with clear branching options — use "
    " `AskUserQuestion` ONLY when you can't reasonably pick a default. "
    " Don't ask just to be polite."
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
    "`~/.orion/skills/` exists for skills that should outlast / cross "
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
            f" `{ws}`\n"
            "When the user mentions 'skill / memory / mcp library' or 'this "
            "project's …', use the **project-scoped** paths first:\n"
            f"- Project skills: `{ws}/.orion/skills/`\n"
            f"- Project memory: `{ws}/.orion/memory/`\n"
            f"- Project MCP config: `{ws}/.orion/mcp.json`\n"
            f"- Project instructions: `{ws}/.orion/instructions.md`\n"
            "Personal libraries still exist at "
            "`~/.orion/users/cowork-local/{skills,memory}/` and "
            "`~/.orion/mcp.json`, but **only use them if the user "
            "explicitly says 'personal' / 'app-level' / 'global'**."
        ) + _SYSTEM_LEVEL_NOTE
    return (
        "\n\n# This is a personal chat (not in a project)\n"
        "Use the personal libraries — that's the only scope here:\n"
        "- Personal skills: `~/.orion/users/cowork-local/skills/`\n"
        "- Personal memory: `~/.orion/users/cowork-local/memory/`\n"
        "- Personal MCP: `~/.orion/mcp.json`\n"
        "- Default workspace `~/.orion/users/cowork-local/workspace/` "
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
        # D 下:MCP manager(lazy start)
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
        # Plan Mode— `set_plan_mode(enabled=true)` 設這個 flag,
        # 下次 `_build_conversation` 看到就 inject ACTIVE PlanModeState 並清掉。
        # 不直接改 DB 是因為 ACTIVE 需要 plan_id / plan_file_path,只在實際 send
        # 開始時才建。
        self._pending_plan_enter: set[str] = set()
        # In-flight plan_approve/reject 守 (避免 RPC vs 進行中 conv.send 競態)
        self._plan_action_lock: dict[str, asyncio.Lock] = {}
        # Notifier 由 __main__ 在 RpcServer build 後注入(寫 stdout 無 id frame)。
        # SchedulerEngine.fire / record_compaction 等背景事件透過這個推給 main。
        self._notifier: Any = None
        # 背景排程引擎(sidecar 開著時跑;ensure_engine 完成後第一次 send 順手 start)
        self._scheduler = SchedulerEngine(self)
        self._scheduler_started = False
        self._scheduler_start_lock = asyncio.Lock()

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
                except Exception as e: # noqa: BLE001
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
                except Exception as e: # noqa: BLE001
                    print(
                        f"[storage] cleanup failed: {e}",
                        file=sys.stderr, flush=True,
                    )
                # Plan Mode crash recovery
                # 啟動時若有 session 卡在 AWAITING_APPROVAL → fire-and-forget
                # 排程一次 re-emit notification(等 notifier 已注入 + renderer 連上)
                asyncio.create_task(self._plan_mode_startup_recovery())
                # Plan file GC — 孤兒 + 30 天舊
                asyncio.create_task(self._cleanup_orphan_plan_files())
                # TTS cache GC— 30 天舊 cache 自動清
                asyncio.create_task(self._cleanup_tts_cache())
                # AgentTool default-disabled seeding
                # 首次跑這版時把 "Agent" 加進 disabled_tools — LLM spawn 子 agent
                # 會放大 token cost,user 自己在 Settings → 工具 開才放手。
                try:
                    await self._seed_default_disabled_tools()
                except Exception as e: # noqa: BLE001
                    print(
                        f"[storage] disabled_tools seeding failed: {e}",
                        file=sys.stderr, flush=True,
                    )
            return self._engine

    # 版本化的 default-disabled seed — 每條 version 是一次性 additive operation。
    # 將來想再加 default-off 工具,擴一條 vN 就好(已 apply 過的 version 不會 re-run)。
    _DEFAULT_DISABLED_SEEDS: dict[str, frozenset[str]] = { # noqa: RUF012
        "v1": frozenset({"Agent"}),
        "v2": frozenset({
            # System group(目前只剩 Sleep — autonomous loop 偶爾用,Cowork chat
            # 場景幾乎用不到)
            "Sleep",
            # Browser group(playwright + system Chrome,LLM 自呼會跳新 Chrome
            # window,user 應該顯式 enable)
            "BrowserNavigate", "BrowserBack", "BrowserForward",
            "BrowserClick", "BrowserType", "BrowserScroll",
            "BrowserScreenshot", "BrowserReadPage",
            "BrowserWaitFor", "BrowserClose",
        }),
    }

    async def _seed_default_disabled_tools(self) -> None:
        """First-run-after-upgrade:把 host 認為「預設該關」的 tool 名一次性
        seed 進 cowork_prefs.disabled_tools。Marker pref 記已 apply 的 version
        list(CSV),user 之後在 Settings UI 開關都被尊重 — 同一 version 不會
        重複 seed,但新加 vN 還是會補 seed 給已升級的舊 user。"""
        if self._engine is None:
            return
        marker = await storage.get_pref(self._engine, "host_default_disabled_seeded") or ""
        applied = {v.strip() for v in marker.split(",") if v.strip()}
        new_to_add: set[str] = set()
        for version, tool_names in self._DEFAULT_DISABLED_SEEDS.items():
            if version not in applied:
                new_to_add |= tool_names
                applied.add(version)
        if not new_to_add:
            return
        existing = await storage.get_pref(self._engine, "disabled_tools") or ""
        items = {t.strip() for t in existing.split(",") if t.strip()}
        items |= new_to_add
        await storage.set_pref(self._engine, "disabled_tools", ",".join(sorted(items)))
        await storage.set_pref(
            self._engine, "host_default_disabled_seeded", ",".join(sorted(applied)),
        )

    async def _plan_mode_startup_recovery(self) -> None:
        """啟動時若有 session 卡在 AWAITING_APPROVAL,re-emit notification 讓
        renderer 重開 modal。等 5s 給 notifier + renderer 連上。"""
        await asyncio.sleep(5)
        if self._engine is None or self._notifier is None:
            return
        try:
            rows = await storage.list_awaiting_approval_sessions(self._engine)
        except Exception: # noqa: BLE001
            return
        for row in rows:
            await self.notify({
                "event": "plan_mode.awaiting_approval",
                "data": {
                    "session_id": row["session_id"],
                    "plan_id": row["plan_id"],
                    "plan_markdown": row["plan_content"],
                    "plan_file_path": row["plan_file_path"],
                },
            })

    async def _cleanup_orphan_plan_files(self) -> None:
        """掃 ~/.orion/plans/,刪不被任何 session 引用 + mtime > 30 天的孤兒。"""
        import sys
        import time
        from pathlib import Path as _Path
        plan_dir = _Path.home() / ".orion" / "plans"
        if not plan_dir.is_dir():
            return
        if self._engine is None:
            return
        try:
            referenced = await storage.list_referenced_plan_files(self._engine)
        except Exception: # noqa: BLE001
            return
        cutoff = time.time() - 30 * 24 * 3600
        deleted = 0
        for f in plan_dir.iterdir():
            if not f.is_file() or f.suffix != ".md":
                continue
            if str(f) in referenced:
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
            except OSError:
                pass
        if deleted:
            print(
                f"[plan_mode] GC: deleted {deleted} orphan plan files",
                file=sys.stderr, flush=True,
            )

    async def _cleanup_tts_cache(self) -> None:
        """TTS cache GC — 30 天舊 unlink。fire-and-forget,fail 不影響 sidecar。"""
        import sys
        try:
            stats = tts_handlers.cleanup_old_tts_cache(days=30)
        except Exception as e: # noqa: BLE001
            print(f"[tts] cache GC failed: {e}", file=sys.stderr, flush=True)
            return
        if stats["deleted"]:
            print(
                f"[tts] cache GC: deleted {stats['deleted']} files "
                f"({stats['bytes_freed']} bytes)",
                file=sys.stderr, flush=True,
            )

    async def ensure_mcp(self) -> CoworkMcpManager:
        """Lazy start McpManager + supervisor — 首次需要 mcp tools 或 mcp.list 時才連。"""
        async with self._mcp_lock:
            if not self._mcp_started:
                try:
                    await self._mcp.start()
                except Exception: # noqa: BLE001
                    # Start 失敗不該擋 sidecar — 沒 MCP 也能跑 builtin tools
                    pass
                self._mcp_started = True
            return self._mcp

    async def shutdown(self) -> None:
        """sidecar 退出時清理 scheduler + MCP + browser sessions。"""
        try:
            await self._scheduler.stop()
        except Exception: # noqa: BLE001
            pass
        await self._mcp.shutdown()
        # Close 所有開著的 Chrome instance(若有)
        try:
            from orion_cowork_sidecar.browser_tools import close_all_browser_sessions
            await close_all_browser_sessions()
        except ImportError:
            pass

    def set_notifier(self, notifier: Any) -> None:
        """由 __main__ 注入 RpcServer._write_frame,讓背景事件能推 frame 給 main。"""
        self._notifier = notifier

    async def notify(self, frame: dict[str, Any]) -> None:
        """推一個 notification frame 給 main(無 id)。fallback 走 stderr log。"""
        if self._notifier is None:
            print(
                f"[handlers] no notifier — dropping frame {frame.get('event')}",
                file=__import__('sys').stderr, flush=True,
            )
            return
        await self._notifier(frame)

    async def ensure_scheduler_started(self) -> None:
        if self._scheduler_started:
            return
        async with self._scheduler_start_lock:
            if self._scheduler_started:
                return
            try:
                await self._scheduler.start()
                self._scheduler_started = True
            except Exception as e: # noqa: BLE001
                import sys
                print(
                    f"[handlers] scheduler start failed: {e}",
                    file=sys.stderr, flush=True,
                )

    # ─── Dispatch table ─────────────────────────────────────────────────
    def methods(self) -> dict[str, Any]:
        return {
            **schedule_handlers.bind_schedule_handlers(self),
            "ping": self.ping,
            "models.list": self.models_list,
            "ollama.list_models": self.ollama_list_models,
            "ollama.health": self.ollama_health,
            "conversation.create": self.conversation_create,
            "conversation.send": self.conversation_send,
            "conversation.abort": self.conversation_abort,
            "conversation.list": self.conversation_list,
            "conversation.search": self.conversation_search,
            "conversation.delete": self.conversation_delete,
            "conversation.delete_many": self.conversation_delete_many,
            "conversation.rename": self.conversation_rename,
            "conversation.set_starred": self.conversation_set_starred,
            "conversation.get_workspace": self.conversation_get_workspace,
            "conversation.set_workspace": self.conversation_set_workspace,
            "conversation.set_project": self.conversation_set_project,
            "project.list": self.project_list,
            "project.get": self.project_get,
            "project.create": self.project_create,
            "project.update": self.project_update,
            "project.delete": self.project_delete,
            "collaboration.create": self.collaboration_create,
            "collaboration.list": self.collaboration_list,
            "collaboration.get": self.collaboration_get,
            "collaboration.delete": self.collaboration_delete,
            "collaboration.add_pane": self.collaboration_add_pane,
            "collaboration.remove_pane": self.collaboration_remove_pane,
            "collaboration.update_pane_position": self.collaboration_update_pane_position,
            "collaboration.cost_summary": self.collaboration_cost_summary,
            "memory.list": memory_handlers.memory_list,
            "memory.get": memory_handlers.memory_get,
            "memory.write": memory_handlers.memory_write,
            "memory.delete": memory_handlers.memory_delete,
            "skill.list": skill_handlers.skill_list,
            "skill.get": skill_handlers.skill_get,
            "skill.write": skill_handlers.skill_write,
            "skill.import_folder": skill_handlers.skill_import_folder,
            "skill.delete": skill_handlers.skill_delete,
            "role.list": role_handlers.role_list,
            "role.get": role_handlers.role_get,
            "role.write": role_handlers.role_write,
            "role.delete": role_handlers.role_delete,
            "prefs.get_all": self.prefs_get_all,
            "prefs.set": self.prefs_set,
            "tools.list_builtin": self.tools_list_builtin,
            "conversation.messages": self.conversation_messages,
            "conversation.attachment": self.conversation_attachment,
            "attachment.prepare_drop": self.attachment_prepare_drop,
            "attachment.save_uploaded": self.attachment_save_uploaded,
            "workspace.list_files": self.workspace_list_files,
            "conversation.regenerate": self.conversation_regenerate,
            "conversation.truncate": self.conversation_truncate,
            "conversation.fork": self.conversation_fork,
            "conversation.count_fork_descendants": self.conversation_count_fork_descendants,
            "conversation.tool_approval": self.conversation_tool_approval,
            "conversation.ask_user_reply": self.conversation_ask_user_reply,
            "conversation.set_permission_mode": self.conversation_set_permission_mode,
            "conversation.set_plan_mode": self.conversation_set_plan_mode,
            "conversation.plan_approve": self.conversation_plan_approve,
            "conversation.plan_reject": self.conversation_plan_reject,
            "conversation.plan_status": self.conversation_plan_status,
            "conversation.stats": self.conversation_stats,
            "conversation.get_budget": self.conversation_get_budget,
            "conversation.set_budget": self.conversation_set_budget,
            "conversation.context_breakdown": self.conversation_context_breakdown,
            "conversation.compact": self.conversation_compact,
            "permissions.get": self.permissions_get,
            "permissions.set": self.permissions_set,
            "stt.transcribe": stt_handlers.stt_transcribe,
            "stt.status": self.stt_status,
            "tts.synthesize": tts_handlers.tts_synthesize,
            "tts.status": tts_handlers.tts_status,
            "mcp.list": self.mcp_list,
            "mcp.reconnect": self.mcp_reconnect,
            "mcp.config_list": self.mcp_config_list,
            "mcp.config_upsert": self.mcp_config_upsert,
            "mcp.config_delete": self.mcp_config_delete,
            "maintenance.migrate_attachments": self.maintenance_migrate_attachments,
            "maintenance.cleanup_blobs": self.maintenance_cleanup_blobs,
            "backup.preview": lambda p: backup_handlers.backup_preview(self, p),
            "backup.export": lambda p: backup_handlers.backup_export(self, p),
            "backup.inspect": lambda p: backup_handlers.backup_inspect(self, p),
            "backup.restore": lambda p: backup_handlers.backup_restore(self, p),
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
        # 走 proxy 時 client 不必有直接 key — UI 仍標 configured,但同時 flag
        # via_proxy=True 讓 UI 顯⚠「未驗證」徽章,提示「我們沒真的 ping proxy
        # 確認 token 合法 / upstream 可達」— proxy 那邊缺 key / token 不合法都
        # 等真實 send 時才會回 403/503,不在這裡擋。
        via_proxy = bool(os.environ.get("ORION_MODEL_PROXY_URL"))
        # list_catalog() 回 {"providers": [{"id", "label", "models": [...]}, ...]}
        providers = catalog.get("providers", [])
        if isinstance(providers, list):
            for p in providers:
                if not isinstance(p, dict):
                    continue
                pid = p.get("id", "")
                if pid == "ollama":
                    # Ollama 不需要 API key,但要標 "available" 看 Ollama daemon 是否在跑
                    p["api_key_configured"] = True
                    p["dynamic"] = True
                elif pid in env_map and via_proxy:
                    p["api_key_configured"] = True
                    p["via_proxy"] = True
                else:
                    env_name = env_map.get(pid)
                    p["api_key_configured"] = bool(env_name and os.environ.get(env_name))
        yield {
            "event": "models",
            "data": catalog,
            "final": True,
        }

    async def ollama_list_models(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """呼 `GET /api/tags`,回 user 在 Ollama 已 pull 的 model 列表。

        Params:
            base_url: 可選,override 預設 base URL(否則走 OLLAMA_HOST env / localhost)。

        Yields:
            event=ollama_models, data={models: [{name, size, ...}], base_url}
            event=error 若連不上。
        """
        from orion_model.ollama_provider import list_ollama_models, resolve_ollama_base_url

        base_url = params.get("base_url") if isinstance(params, dict) else None
        if base_url is not None and not isinstance(base_url, str):
            base_url = None
        resolved = resolve_ollama_base_url(base_url)
        try:
            models = await list_ollama_models(base_url=base_url)
        except RuntimeError as e:
            yield {
                "event": "error",
                "data": {
                    "code": "OLLAMA_UNREACHABLE",
                    "message": str(e),
                    "base_url": resolved,
                },
                "final": True,
            }
            return
        yield {
            "event": "ollama_models",
            "data": {"models": models, "base_url": resolved},
            "final": True,
        }

    async def ollama_health(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """呼 `GET /api/version` 確認 Ollama 在跑。

        Yields:
            event=ollama_health, data={ok, version?, error?, base_url}
        """
        from orion_model.ollama_provider import check_ollama_health

        base_url = params.get("base_url") if isinstance(params, dict) else None
        if base_url is not None and not isinstance(base_url, str):
            base_url = None
        result = await check_ollama_health(base_url=base_url)
        yield {
            "event": "ollama_health",
            "data": result,
            "final": True,
        }

    async def conversation_create(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        provider_name = params.get("provider", "anthropic")
        model = params.get("model", "claude-sonnet-4-6")
        project_id = params.get("project_id") # 可選
        workspace_dir = params.get("workspace_dir") # 可選
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

        # Budget pre-check— exceeded flag 已標 + cap 仍存在 → 拒絕
        # 給 user 看到 banner 提示「加額度或新開 session」。Raise cap 在
        # set_budget RPC 內會 reset flag。
        budget_info = await storage.get_session_budget(engine, sid)
        if budget_info["exceeded"] and budget_info["budget_usd_cap"] is not None:
            current = _compute_cumulative_cost(conv)
            yield {
                "event": "error",
                "data": {
                    "code": "BUDGET_EXCEEDED",
                    "message": (
                        f"Session budget exceeded "
                        f"(${current:.4f} / ${budget_info['budget_usd_cap']:.2f}). "
                        "Raise the cap in the right panel to continue."
                    ),
                    "current_usd": current,
                    "budget_usd_cap": budget_info["budget_usd_cap"],
                },
                "final": True,
            }
            return

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
                    print(f"[sidecar] attachment[{i}] dropped: not a dict (got {type(a).__name__})", file=sys.stderr, flush=True)
                    continue
                media_type = a.get("media_type") or "image/png"
                data = a.get("data")
                if not isinstance(data, str) or not data:
                    print(
                        f"[sidecar] attachment[{i}] dropped: bad data "
                        f"(type={type(data).__name__}, len={len(data) if isinstance(data,str) else 'N/A'})",
                        file=sys.stderr, flush=True,
                    )
                    continue
                try:
                    images.append(ImageBlock(media_type=media_type, data=data))
                    print(
                        f"[sidecar] attachment[{i}] OK: {media_type} "
                        f"{len(data)}b base64",
                        file=sys.stderr, flush=True,
                    )
                except Exception as e: # noqa: BLE001
                    print(f"[sidecar] attachment[{i}] ImageBlock build failed: {e}", file=sys.stderr, flush=True)
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

        # ─── Plan Mode wiring──────────────────────────────
        # 三條路:
        # (a) `_pending_plan_enter[sid]` 為 True(user 剛點 /plan 開啟)
        # → inject 新 ACTIVE state,append 一條 system-style user msg
        # 告知 LLM 進入 plan mode
        # (b) DB 有 active / awaiting_approval state(跨 turn 持續)
        # → reconstruct PlanModeState 注入
        # (c) AWAITING_APPROVAL:拒絕新 send(等 approve/reject 才放行)
        injected_plan_state: PlanModeState | None = None
        if sid in self._pending_plan_enter:
            from pathlib import Path as _Path
            from uuid import uuid4 as _uuid4
            plan_dir = _Path.home() / ".orion" / "plans"
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_id = _uuid4()
            plan_file = plan_dir / f"plan-{plan_id.hex[:12]}.md"
            try:
                plan_file.touch()
            except OSError:
                pass
            injected_plan_state = PlanModeState(
                status=PlanModeStatus.ACTIVE,
                plan_id=plan_id,
                plan_file=plan_file,
                plan_content="",
                entered_at_message_index=len(conv.state_messages),
            )
            self._pending_plan_enter.discard(sid)
            # Append a synthetic system-style user msg so LLM knows we entered
            # plan mode without faking a tool call in history.
            from orion_model.types import NormalizedMessage
            conv.state_messages.append(NormalizedMessage(
                role="user",
                content=(
                    "[System: User enabled Plan Mode. Investigate via Read / Grep / "
                    "Glob / WebFetch / Skill / TodoWrite / AskUserQuestion only — "
                    "Bash / Write / Edit are blocked. When ready, call ExitPlanMode "
                    "with a complete markdown plan for user review.]"
                ),
            ))
        else:
            db_plan = await storage.get_plan_state(engine, sid)
            if db_plan is not None:
                status_enum = PlanModeStatus(db_plan["status"])
                if status_enum == PlanModeStatus.AWAITING_APPROVAL:
                    yield {
                        "event": "error",
                        "data": {
                            "code": "PLAN_AWAITING_APPROVAL",
                            "message": (
                                "A plan is awaiting your approval — call "
                                "plan_approve or plan_reject before continuing."
                            ),
                        },
                        "final": True,
                    }
                    self._aborts.pop(sid, None)
                    return
                if status_enum == PlanModeStatus.ACTIVE:
                    from pathlib import Path as _Path
                    pid = db_plan.get("plan_id")
                    pfp = db_plan.get("plan_file_path")
                    injected_plan_state = PlanModeState(
                        status=PlanModeStatus.ACTIVE,
                        plan_id=UUID(pid) if pid else None,
                        plan_file=_Path(pfp) if pfp else None,
                        plan_content=db_plan.get("plan_content") or "",
                        entered_at_message_index=db_plan.get("entered_at_message_index"),
                    )
        if injected_plan_state is not None:
            ctx.plan_mode_state = injected_plan_state

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
        # 切 mode 那 turn BP 2 重寫,之後又穩定
        # 3. conv.tools byte-identical(AskUserQuestion 永遠在)
        # 4. Mode 行為差異走 asker callback 動態 dispatch:
        # - Ask 模式 → 推 ask_user_question frame 等 user reply
        # - Act 模式 → auto-decide asker 回個 hint 給 LLM 自己 decide
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
            except Exception as e: # noqa: BLE001
                pre_result = None
                print(f"[sidecar] auto-compact failed: {e}", file=sys.stderr, flush=True)
            if pre_result is not None and pre_result.was_compacted:
                # DB soft-delete:把前 N 筆 row 標 compacted_out + append tombstone。
                # 舊訊息 row 留著,UI scroll 回頭仍看得到(灰化顯示),LLM resume 跳過。
                # N = 原 state_messages 長度 - (新長度 - 1) // -1 扣掉 tombstone 本身
                kept = pre_result.kept_message_count
                compacted_count = pre_compact_state_count - (kept - 1)
                tombstone_msg = conv.state_messages[0]
                try:
                    await storage.record_compaction(
                        engine, sid,
                        compacted_count=compacted_count,
                        tombstone_msg=tombstone_msg,
                    )
                except Exception as e: # noqa: BLE001
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
            except Exception as e: # noqa: BLE001
                # 解開 anyio/TaskGroup 的 ExceptionGroup 找真實 cause,再 map
                # 成 user-friendly code + message。Sidecar log 完整 trace,
                # renderer 只看簡潔訊息(避免 ⚠ {"code":"ExceptionGroup",...} 醜)。
                import sys as _sys
                import traceback as _tb
                code, message = _format_send_error(e)
                print(
                    f"[sidecar] conversation.send failed for {sid[:8]}: "
                    f"{code} — {message}\n{_tb.format_exc()}",
                    file=_sys.stderr, flush=True,
                )
                await out_queue.put({
                    "error": {"code": code, "message": message},
                    "final": True,
                })
            finally:
                await out_queue.put(None) # sentinel:producer done

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
                except (asyncio.CancelledError, Exception): # noqa: BLE001
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
                except Exception: # noqa: BLE001
                    # Persistence 失敗不該炸 sidecar — 之後重 send 還是會嘗試
                    pass
            # ─── Plan Mode persist + notification──────────
            # Read ctx 上被 tools 修改過的 state,寫回 DB。狀態變化時 emit
            # 對應 notification 讓 renderer 更新 UI。
            try:
                await self._persist_plan_state_and_notify(sid, ctx)
            except Exception as e: # noqa: BLE001
                print(
                    f"[plan_mode] persist/notify failed for {sid[:8]}: {e}",
                    file=__import__('sys').stderr, flush=True,
                )
            # ─── Budget post-check─────────────────────────
            # 累積成本超 cap → 設 exceeded flag + emit notification,renderer
            # 收到後浮 banner 提示。下次 send 會被 pre-check 攔下。
            try:
                await self._check_budget_and_notify(sid, conv, engine)
            except Exception as e: # noqa: BLE001
                print(
                    f"[budget] check/notify failed for {sid[:8]}: {e}",
                    file=__import__('sys').stderr, flush=True,
                )
            # ─── Persist cumulative token usage────────────
            # 寫 conv.stats 進 cowork_session_ext 累積欄位,跨 sidecar 重啟
            # cost 才不會歸 0。在這裡呼是因為 turn 結束才有當輪累積數字。
            try:
                stats = conv.stats
                await storage.persist_session_stats(
                    engine, sid,
                    input_tokens=stats.input_tokens,
                    output_tokens=stats.output_tokens,
                    cache_read_tokens=stats.cache_read_tokens,
                    cache_creation_tokens=stats.cache_creation_tokens,
                    turns=stats.turns,
                )
            except Exception as e: # noqa: BLE001
                print(
                    f"[stats] persist failed for {sid[:8]}: {e}",
                    file=__import__('sys').stderr, flush=True,
                )

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

        async def _gate(tool: Any, tool_input: dict[str, Any], ctx: AgentContext) -> PermissionResult: # noqa: ARG001
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
            "google": "GOOGLE_STT_API_KEY", # Google STT 沒走 proxy,直連檢查
        }
        # OpenAI 走 proxy 時 client 不必直接有 key。Google 不走 proxy(audio/stt.py
        # 的 _google_base 永遠回真實 https://speech.googleapis.com),維持直連檢查。
        openai_via_proxy = bool(os.environ.get("ORION_MODEL_PROXY_URL"))
        providers = catalog.get("providers", [])
        if isinstance(providers, list):
            for p in providers:
                if not isinstance(p, dict):
                    continue
                pid = p.get("id", "")
                if pid == "openai" and openai_via_proxy:
                    p["api_key_configured"] = True
                    p["via_proxy"] = True
                else:
                    env_name = env_map.get(pid)
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
        回: { scope, allow: [...], deny: [...] }
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
        except Exception as e: # noqa: BLE001
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
        except Exception as e: # noqa: BLE001
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
        cache_read_price = pricing.get("cache_read", input_price) # fallback to input
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
        except Exception: # noqa: BLE001 — fallback,不擋整個 RPC
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
            except Exception: # noqa: BLE001
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
                    pdir = Path(proj.workspace_dir) / ".orion" / "skills"
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
        except Exception: # noqa: BLE001
            pass
        skills_tokens = sum(d["tokens"] for d in skills_detail)

        # ─── 5) Messages ────────────────────────────────────────────────
        messages_tokens = estimate_token_count(conv.state_messages)

        # ─── 6/7) Buffer + Free ─────────────────────────────────────────
        max_context = conv.provider.capabilities.max_context_tokens
        # threshold 優先序:RPC params(renderer 帶當下 settings)
        # > conv.auto_compact_threshold(上輪 send 寫入的)
        # > 預設 0.8。
        # 沒這 fallback 鏈,user 還沒送任何 prompt 就跑 /context 時 threshold 會
        # 走預設值,跟 Settings 顯示的不一致(看起來像「亂寫」)。
        threshold: float = 0.8
        if conv.auto_compact_threshold:
            threshold = conv.auto_compact_threshold
        rpc_threshold = params.get("auto_compact_threshold")
        if isinstance(rpc_threshold, (int, float)) and 0.1 <= rpc_threshold <= 0.99:
            threshold = float(rpc_threshold)
            conv.auto_compact_threshold = threshold # 同時 sync 進 conv,下次 send 不會回退
        # round 取代 int — 避免 1_000_000 * 0.2 因浮點落到 199_999
        autocompact_buffer_tokens = round(max_context * (1.0 - threshold))
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
        except Exception as e: # noqa: BLE001
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
        except Exception as e: # noqa: BLE001
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

    # ─── Plan Mode RPC────────────────────────────────────

    def _plan_lock(self, sid: str) -> asyncio.Lock:
        if sid not in self._plan_action_lock:
            self._plan_action_lock[sid] = asyncio.Lock()
        return self._plan_action_lock[sid]

    async def _persist_plan_state_and_notify(
        self, sid: str, ctx: AgentContext,
    ) -> None:
        """Send loop 結束後呼叫。Diff DB vs ctx,寫回 + emit notification。"""
        engine = await self.ensure_engine()
        live = ctx.plan_mode_state
        if not isinstance(live, PlanModeState) or live.status == PlanModeStatus.INACTIVE:
            # state 是 INACTIVE 或從未設過 → 清 DB(若有殘留)
            existing = await storage.get_plan_state(engine, sid)
            if existing is not None:
                await storage.save_plan_state(engine, sid, status="idle")
            return
        # ACTIVE / AWAITING_APPROVAL — persist
        plan_file_path = str(live.plan_file) if live.plan_file else None
        plan_id_str = live.plan_id.hex if live.plan_id else None
        await storage.save_plan_state(
            engine, sid,
            status=live.status.value,
            plan_id=plan_id_str,
            plan_file_path=plan_file_path,
            plan_content=live.plan_content or None,
            entered_at_message_index=live.entered_at_message_index,
        )
        if live.status == PlanModeStatus.AWAITING_APPROVAL:
            await self.notify({
                "event": "plan_mode.awaiting_approval",
                "data": {
                    "session_id": sid,
                    "plan_id": plan_id_str,
                    "plan_markdown": live.plan_content,
                    "plan_file_path": plan_file_path,
                },
            })

    async def _check_budget_and_notify(
        self, sid: str, conv: Any, engine: Any,
    ) -> None:
        """Turn 結束後檢查累積成本是否超 cap。超過 → set exceeded flag + notify。

        Cap=None(未設) → 不做事。已經 exceeded=True 不再重發通知,避免每 turn 都炸。
        """
        info = await storage.get_session_budget(engine, sid)
        cap = info["budget_usd_cap"]
        if cap is None:
            return
        current = _compute_cumulative_cost(conv)
        if current >= cap and not info["exceeded"]:
            await storage.mark_budget_exceeded(engine, sid, True)
            await self.notify({
                "event": "budget.exceeded",
                "data": {
                    "session_id": sid,
                    "current_usd": current,
                    "budget_usd_cap": cap,
                },
            })

    async def conversation_get_budget(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """讀 session budget cap + 目前累積成本。"""
        sid = params.get("session_id")
        if not isinstance(sid, str) or not sid:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        info = await storage.get_session_budget(engine, sid)
        # 算當前累積 cost — 若 conv 不在 memory 就 0(沒跑過 turn,沒花到錢)
        conv = self._conversations.get(sid)
        current = _compute_cumulative_cost(conv) if conv is not None else 0.0
        yield {
            "event": "budget",
            "data": {
                "session_id": sid,
                "budget_usd_cap": info["budget_usd_cap"],
                "exceeded": info["exceeded"],
                "current_usd": current,
            },
            "final": True,
        }

    async def conversation_set_budget(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """設 / 清 session budget cap。傳 0 或 null 等於不限。

        設新 cap 會 reset exceeded flag — 讓 user raise cap 後可繼續 send。
        若新 cap 仍 < current cost,下一次 turn 結束時會再次觸發 exceeded。
        """
        sid = params.get("session_id")
        cap_raw = params.get("budget_usd_cap")
        if not isinstance(sid, str) or not sid:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
                "final": True,
            }
            return
        if cap_raw is not None and not isinstance(cap_raw, (int, float)):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "budget_usd_cap must be number or null"},
                "final": True,
            }
            return
        cap_value: float | None = float(cap_raw) if cap_raw is not None else None
        engine = await self.ensure_engine()
        await storage.set_session_budget(engine, sid, cap_value)
        info = await storage.get_session_budget(engine, sid)
        yield {
            "event": "budget_saved",
            "data": {
                "session_id": sid,
                "budget_usd_cap": info["budget_usd_cap"],
                "exceeded": info["exceeded"],
            },
            "final": True,
        }

    async def conversation_set_plan_mode(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """User 切 Plan Mode 開關(`/plan` slash 或 PermissionModePill)。

        enabled=true:設 pending flag,下次 send 時 inject ACTIVE state
        enabled=false:若當前 active/awaiting → reject_and_exit + abort 進行中 send
        """
        sid = params.get("session_id")
        enabled = params.get("enabled")
        if not isinstance(sid, str) or not isinstance(enabled, bool):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id + enabled required"},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        async with self._plan_lock(sid):
            if enabled:
                self._pending_plan_enter.add(sid)
                await self.notify({
                    "event": "plan_mode.entered",
                    "data": {"session_id": sid},
                })
                yield {
                    "event": "plan_mode_set",
                    "data": {"session_id": sid, "enabled": True, "status": "pending"},
                    "final": True,
                }
                return
            # disable
            self._pending_plan_enter.discard(sid)
            db_plan = await storage.get_plan_state(engine, sid)
            if db_plan is not None:
                # 嘗試 reject_and_exit;若進行中的 ctx 也存在,同步更新
                from pathlib import Path as _Path
                plan_file_path = db_plan.get("plan_file_path")
                # 刪 plan_file(若存在)
                if plan_file_path:
                    try:
                        _Path(plan_file_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                await storage.save_plan_state(engine, sid, status="idle")
                # Abort in-flight send 若有
                live_ctx = self._aborts.get(sid)
                if isinstance(live_ctx, AgentContext):
                    live_ctx.abort_event.set()
                    if isinstance(live_ctx.plan_mode_state, PlanModeState):
                        live_ctx.plan_mode_state = PlanModeState()
            await self.notify({
                "event": "plan_mode.exited",
                "data": {"session_id": sid},
            })
            yield {
                "event": "plan_mode_set",
                "data": {"session_id": sid, "enabled": False, "status": "idle"},
                "final": True,
            }

    async def conversation_plan_approve(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """User 按 Approve:state → INACTIVE,注入 'Approved, proceed' user msg
        但**不**自動觸發 send(renderer 自己呼 conversation.send 接續)。
        """
        sid = params.get("session_id")
        follow_up = params.get("follow_up") or "Approved. Proceed with the plan."
        if not isinstance(sid, str):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        async with self._plan_lock(sid):
            # 若 in-flight send 還沒結束 → 拒絕(approve 該在 turn 結束後才呼)
            if sid in self._aborts:
                yield {
                    "event": "error",
                    "data": {
                        "code": "PLAN_SEND_IN_FLIGHT",
                        "message": "wait for the planning turn to finish before approving",
                    },
                    "final": True,
                }
                return
            db_plan = await storage.get_plan_state(engine, sid)
            if db_plan is None or db_plan["status"] != PlanModeStatus.AWAITING_APPROVAL.value:
                yield {
                    "event": "error",
                    "data": {
                        "code": "PLAN_NOT_AWAITING",
                        "message": "no plan awaiting approval for this session",
                    },
                    "final": True,
                }
                return
            # State → INACTIVE,DB 清空
            await storage.save_plan_state(engine, sid, status="idle")
            # 同步 in-memory conv 若有(下次 send 重建 ctx,反正 ctx 是新的)
            await self.notify({
                "event": "plan_mode.approved",
                "data": {"session_id": sid},
            })
            yield {
                "event": "plan_approved",
                "data": {
                    "session_id": sid,
                    "follow_up": follow_up,
                    "plan_file_path": db_plan.get("plan_file_path"),
                },
                "final": True,
            }

    async def conversation_plan_reject(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """User 按 Reject(可帶 feedback):state → INACTIVE,刪 plan_file,
        回傳 follow_up text 給 renderer 自行送下一輪 conversation.send。
        """
        sid = params.get("session_id")
        feedback = params.get("feedback") or ""
        if not isinstance(sid, str):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        async with self._plan_lock(sid):
            if sid in self._aborts:
                yield {
                    "event": "error",
                    "data": {
                        "code": "PLAN_SEND_IN_FLIGHT",
                        "message": "wait for the planning turn to finish before rejecting",
                    },
                    "final": True,
                }
                return
            db_plan = await storage.get_plan_state(engine, sid)
            if db_plan is None or db_plan["status"] != PlanModeStatus.AWAITING_APPROVAL.value:
                yield {
                    "event": "error",
                    "data": {
                        "code": "PLAN_NOT_AWAITING",
                        "message": "no plan awaiting approval for this session",
                    },
                    "final": True,
                }
                return
            from pathlib import Path as _Path
            plan_file_path = db_plan.get("plan_file_path")
            if plan_file_path:
                try:
                    _Path(plan_file_path).unlink(missing_ok=True)
                except OSError:
                    pass
            await storage.save_plan_state(engine, sid, status="idle")
            feedback_clean = feedback.strip()
            follow_up = (
                f"Plan rejected. {feedback_clean} Don't proceed with that plan."
                if feedback_clean
                else "Plan rejected. Try a different approach. Don't proceed with that plan."
            )
            await self.notify({
                "event": "plan_mode.rejected",
                "data": {"session_id": sid, "feedback": feedback_clean},
            })
            yield {
                "event": "plan_rejected",
                "data": {"session_id": sid, "follow_up": follow_up},
                "final": True,
            }

    async def conversation_plan_status(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """純查詢:回 session 當前 plan_mode_state(給 renderer mount 時 re-hydrate)。"""
        sid = params.get("session_id")
        if not isinstance(sid, str):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        db_plan = await storage.get_plan_state(engine, sid)
        if db_plan is None and sid in self._pending_plan_enter:
            # /plan toggle 開了但還沒第一 send → 視同 active(讓 banner 顯示)
            yield {
                "event": "plan_status",
                "data": {"session_id": sid, "status": "pending"},
                "final": True,
            }
            return
        if db_plan is None:
            yield {
                "event": "plan_status",
                "data": {"session_id": sid, "status": "idle"},
                "final": True,
            }
            return
        yield {
            "event": "plan_status",
            "data": {
                "session_id": sid,
                "status": db_plan["status"],
                "plan_id": db_plan.get("plan_id"),
                "plan_markdown": db_plan.get("plan_content"),
                "plan_file_path": db_plan.get("plan_file_path"),
            },
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
            return # 兩邊都 empty,無事可做
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

    async def _resolve_uploads_dir(
        self, sid: str, engine: AsyncEngine
    ) -> "Path":
        """拖檔 / 上傳暫存位置。優先用 workspace,沒設則 ~/.orion/uploads/<sid>/。"""
        from pathlib import Path
        ws = await self._resolve_session_cwd(sid, engine)
        if ws is not None:
            return ws / ".orion" / "uploads"
        return Path.home() / ".orion" / "uploads" / sid

    @staticmethod
    def _safe_dest(target_dir: "Path", filename: str) -> "Path":
        """同名衝突時加時間戳尾碼。filename 內含 path 分隔符會被丟掉(取 basename)。"""
        from datetime import datetime
        from pathlib import PurePath
        basename = PurePath(filename).name or "file"
        candidate = target_dir / basename
        if not candidate.exists():
            return candidate
        # 加時間戳尾碼:foo.py → foo-20260518-211200.py
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = candidate.stem
        suffix = candidate.suffix
        return target_dir / f"{stem}-{stamp}{suffix}"

    async def workspace_list_files(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """列出 workspace 內檔案,給 @file: mention popup 用。

        Skip 重的目錄(node_modules / .git / __pycache__ / dist / build / .venv /
        target / .next / .orion/uploads),最多回 max 條(預設 500)。

        Params: {session_id, max?: int}
        Returns: {workspace_dir, files: [{rel_path, abs_path, size}], truncated}
        """
        from pathlib import Path
        SKIP_DIRS = {
            "node_modules", ".git", "__pycache__", "dist", "build",
            ".venv", "venv", "target", ".next", ".turbo", ".cache",
            ".idea", ".vscode", "vendor", ".orion",
        }
        sid = params.get("session_id")
        max_count = params.get("max") if isinstance(params.get("max"), int) else 500
        if not isinstance(sid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        ws = await self._resolve_session_cwd(sid, engine)
        if ws is None:
            yield {
                "event": "workspace_files",
                "data": {"workspace_dir": None, "files": [], "truncated": False},
                "final": True,
            }
            return
        ws_resolved = ws.resolve()
        files: list[dict[str, Any]] = []
        truncated = False
        try:
            for p in _walk_workspace(ws_resolved, SKIP_DIRS):
                if len(files) >= max_count:
                    truncated = True
                    break
                try:
                    stat = p.stat()
                except OSError:
                    continue
                files.append({
                    "rel_path": str(p.relative_to(ws_resolved)),
                    "abs_path": str(p),
                    "size": stat.st_size,
                })
        except OSError:
            pass
        yield {
            "event": "workspace_files",
            "data": {
                "workspace_dir": str(ws_resolved),
                "files": files,
                "truncated": truncated,
            },
            "final": True,
        }

    async def attachment_prepare_drop(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Drag-drop 檔案進對話前的前置處理。

        - 若 source_path 在 session workspace 之下 → 不 copy,inject 原 path
          (project 內檔,LLM 改它就是 user 要的)
        - 否則 → copy 到 <workspace>/.orion/uploads/<safe_name>,inject 新 path
          (外部檔,LLM 只看 copy,user 原檔不會被動)

        Params: {session_id, source_path}
        Returns: {final_path, copied: bool, in_workspace: bool}
        """
        from pathlib import Path
        import shutil
        sid = params.get("session_id")
        source_path_raw = params.get("source_path")
        if not isinstance(sid, str) or not isinstance(source_path_raw, str) or not source_path_raw:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id + source_path required"},
                "final": True,
            }
            return
        source_path = Path(source_path_raw)
        if not source_path.is_file():
            yield {
                "event": "error",
                "data": {"code": "FILE_NOT_FOUND", "message": f"{source_path} not a file"},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        ws = await self._resolve_session_cwd(sid, engine)
        # 檔在 workspace 之下 → 就地用
        if ws is not None:
            try:
                source_resolved = source_path.resolve()
                ws_resolved = ws.resolve()
                if str(source_resolved).startswith(str(ws_resolved) + "/") or source_resolved == ws_resolved:
                    yield {
                        "event": "attachment_staged",
                        "data": {
                            "final_path": str(source_resolved),
                            "copied": False,
                            "in_workspace": True,
                        },
                        "final": True,
                    }
                    return
            except (OSError, RuntimeError):
                pass # resolve 失敗 → 走 copy 路徑
        # 外部檔 → copy 到 uploads dir
        uploads = await self._resolve_uploads_dir(sid, engine)
        uploads.mkdir(parents=True, exist_ok=True)
        dest = self._safe_dest(uploads, source_path.name)
        try:
            shutil.copy2(source_path, dest)
        except OSError as e:
            yield {
                "event": "error",
                "data": {"code": "COPY_FAILED", "message": str(e)},
                "final": True,
            }
            return
        yield {
            "event": "attachment_staged",
            "data": {
                "final_path": str(dest),
                "copied": True,
                "in_workspace": False,
            },
            "final": True,
        }

    async def attachment_save_uploaded(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """File picker 上傳(沒 source_path 路徑只有 base64 content)— 一律寫進
        uploads dir。

        Params: {session_id, filename, content_b64}
        Returns: {final_path}
        """
        import base64 as _b64
        sid = params.get("session_id")
        filename = params.get("filename")
        content_b64 = params.get("content_b64")
        if (
            not isinstance(sid, str) or not isinstance(filename, str)
            or not isinstance(content_b64, str) or not filename
        ):
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id + filename + content_b64 required"},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        uploads = await self._resolve_uploads_dir(sid, engine)
        uploads.mkdir(parents=True, exist_ok=True)
        dest = self._safe_dest(uploads, filename)
        try:
            data = _b64.b64decode(content_b64)
            dest.write_bytes(data)
        except (OSError, ValueError) as e:
            yield {
                "event": "error",
                "data": {"code": "WRITE_FAILED", "message": str(e)},
                "final": True,
            }
            return
        yield {
            "event": "attachment_staged",
            "data": {
                "final_path": str(dest),
                "copied": True,
                "in_workspace": False,
            },
            "final": True,
        }

    async def tools_list_builtin(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """列出所有 builtin tools(按組分),給 Settings → Tools 區渲染用。

        Browser group:Cowork host 自帶(從 `browser_tools` 注 `extra_groups`),
        即使 system 沒裝 Chrome / playwright 仍會列名 — 實際 build_default_tool_set
        註冊時 `is_browser_available()` 不通過就 skip,前端 UI 不需區分。
        Agent group:同樣 Cowork-only(預設 disabled,user 自己開)。
        """
        from orion_cowork_sidecar.browser_tools import browser_tool_group
        from orion_sdk.tools.builtin_set import list_builtin_tool_groups

        agent_group: dict[str, Any] = {
            "group": "Agent",
            "tools": [{"name": AgentTool.name, "description": AgentTool.description}],
        }
        try:
            groups = list_builtin_tool_groups(extra_groups=[browser_tool_group(), agent_group])
        except Exception as e: # noqa: BLE001
            yield {
                "event": "error",
                "data": {"code": "LIST_FAILED", "message": str(e)},
                "final": True,
            }
            return
        yield {
            "event": "tools_builtin",
            "data": {"groups": groups},
            "final": True,
        }

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
        # default_workspace_dir / user_instructions / disabled_tools 變更 →
        # 既有 cached conv 失效(下次 send 用新值,system_prompt / tool list 刷新)
        if key in ("default_workspace_dir", "user_instructions", "disabled_tools"):
            self._conversations.clear()
        yield {"event": "prefs_set", "data": {"key": key}, "final": True}

    def _build_schedule_callbacks(
        self, *, project_id: str | None,
    ) -> dict[str, Any]:
        """包 schedule_handlers RPC handlers 成 SDK callback signature。

        SDK Tool 期望:`async fn(params: dict) -> dict`(raise on error)。
        我們的 RPC handler 是 AsyncIterator yielding frames — 走 helper 轉換。
        """
        sched_methods = schedule_handlers.bind_schedule_handlers(self)

        async def _run(name: str, params: dict[str, Any]) -> dict[str, Any]:
            handler = sched_methods[name]
            data: dict[str, Any] = {}
            async for frame in handler(params):
                if frame.get("event") == "error":
                    err = frame.get("data") or {}
                    code = err.get("code", "ERR")
                    msg = err.get("message", "unknown")
                    raise ValueError(f"{code}: {msg}")
                if isinstance(frame.get("data"), dict):
                    data = frame["data"]
            return data

        async def create(params: dict[str, Any]) -> dict[str, Any]:
            # LLM 沒法自己知 project_id;若當前對話在 project 內,自動補
            if project_id and params.get("scope") == "project" and "project_id" not in params:
                params = {**params, "project_id": project_id}
            return await _run("schedule.write", params)

        async def listing(params: dict[str, Any]) -> dict[str, Any]:
            return await _run("schedule.list", params)

        async def deleting(params: dict[str, Any]) -> dict[str, Any]:
            return await _run("schedule.delete", params)

        async def loop_create(params: dict[str, Any]) -> dict[str, Any]:
            """LLM 透過 LoopCreate tool 呼。params 含:
               name, cron_expr, prompt, target_session_id(SDK 已從 ctx 補)。
            轉成 schedule.write 的 params(trigger_type 一律 prompt)。"""
            target_sid = params.get("target_session_id")
            if not target_sid:
                raise ValueError("target_session_id required")
            return await _run("schedule.write", {
                "name": params.get("name"),
                "cron_expr": params.get("cron_expr"),
                "trigger_type": "prompt",
                "payload": params.get("prompt"),
                "scope": "user", # loop 跟 session bound,scope 概念意義不大
                "target_session_id": target_sid,
            })

    @staticmethod
    def _content_to_text(content: Any) -> str:
        """從 message.content(str | list[block])抽 plain text 給 cross-pane query。"""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
                continue
            if not isinstance(b, dict):
                continue
            btype = b.get("type")
            if btype == "text":
                t = b.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif btype == "tool_use":
                name = b.get("name") or "tool"
                parts.append(f"[tool: {name}]")
            elif btype == "tool_result":
                tc = b.get("content")
                if isinstance(tc, str):
                    parts.append(f"[tool result: {tc[:200]}]")
                elif isinstance(tc, list):
                    parts.append(
                        "[tool result: "
                        + " ".join(
                            x.get("text", "")[:200] for x in tc
                            if isinstance(x, dict)
                        )
                        + "]"
                    )
        return "\n".join(p for p in parts if p)

    def _build_ask_pane_callback(
        self,
        collaboration_id: str,
        engine: AsyncEngine,
    ) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        """組裝 AskPaneTool 用的 callback。

        Closure 抓 collaboration_id + engine + self(讀 _aborts 判斷 target 是否 busy)。
        Tool call 時:
          1. From requesting_session_id 反查 collab(double-check 真在這 collab)
          2. By pane_name 找 target pane
          3. 讀 target session 最近 N 條 message
          4. 判 status:target session_id in self._aborts → running;有訊息 → done;沒訊息 → idle
          5. 若 running,從目前 in-flight ctx 取最近活動描述(可選)
        """
        async def _ask_pane(params: dict[str, Any]) -> dict[str, Any]:
            req_sid = params.get("requesting_session_id")
            pane_name = params.get("pane_name") or ""
            n_recent = int(params.get("n_recent_messages") or 8)
            if not isinstance(req_sid, str) or not isinstance(pane_name, str):
                return {"status": "error", "error": "bad params"}
            # Confirm requester really在這 collab(避免被偽造跨 collab query)
            my_cid, _, _ = await storage.get_collaboration_for_session(engine, req_sid)
            if my_cid != collaboration_id:
                return {
                    "status": "not_found",
                    "pane_name": pane_name,
                    "error": "requester not part of expected collaboration",
                }
            target = await storage.find_collaboration_pane(
                engine, collaboration_id, pane_name,
            )
            if target is None:
                return {"status": "not_found", "pane_name": pane_name}
            target_sid = target.session_id
            # 別自我 query 卡死(LLM 容易誤呼)
            if target_sid == req_sid:
                return {
                    "status": "error",
                    "pane_name": pane_name,
                    "error": "cannot AskPane against yourself",
                }
            # Status:有 in-flight ctx 表 running
            is_running = target_sid in self._aborts
            # 抓 target session 最近 N 條 raw message(user+assistant text)
            try:
                raw_msgs = await storage.load_raw_messages(engine, target_sid)
            except Exception: # noqa: BLE001
                raw_msgs = []
            if not raw_msgs:
                final_status = "running" if is_running else "idle"
                return {
                    "status": final_status,
                    "pane_name": target.pane_name,
                    "pane_role": target.pane_role,
                    "current_action": "thinking..." if is_running else None,
                    "transcript_excerpt": [],
                    "partial_output": None,
                }
            # Tail N 訊息;每條抽 role + text 概要(避免回整 content json)
            # load_raw_messages 回 list[(role, content_json, metadata_json)]
            tail = raw_msgs[-n_recent:]
            excerpt: list[dict[str, Any]] = []
            for m in tail:
                role: str | None = None
                content: Any = None
                if isinstance(m, tuple):
                    role = m[0] if len(m) > 0 else None
                    content = m[1] if len(m) > 1 else None
                elif isinstance(m, dict):
                    role = m.get("role")
                    content = m.get("content")
                else:
                    role = getattr(m, "role", None)
                    content = getattr(m, "content", None)
                text = self._content_to_text(content)
                excerpt.append({"role": role, "text": text[:1200]})
            partial_output = None
            current_action = None
            if is_running:
                # 取最後一條 assistant 部分(可能 stream 中)
                last_assistant = next(
                    (e for e in reversed(excerpt) if e["role"] == "assistant"),
                    None,
                )
                if last_assistant:
                    partial_output = last_assistant["text"]
                    current_action = "streaming response..."
                else:
                    current_action = "processing input..."
                final_status = "running"
            else:
                final_status = "done"
            return {
                "status": final_status,
                "pane_name": target.pane_name,
                "pane_role": target.pane_role,
                "current_action": current_action,
                "transcript_excerpt": excerpt,
                "partial_output": partial_output,
            }

        return _ask_pane

        return {
            "create": create,
            "list": listing,
            "delete": deleting,
            "loop_create": loop_create,
        }

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
        # Disabled tools list 從 prefs 讀(CSV)— 讓使用者在 Settings 開關各組
        disabled_raw = await storage.get_pref(engine, "disabled_tools") or ""
        disabled_set = {t.strip() for t in disabled_raw.split(",") if t.strip()}
        # Schedule callbacks — 讓 LLM 在對話中設定排程。
        # 「對話 → SKILL.md」走既有 `skillify` bundled skill + Write tool,
        # 不需要另一個 SkillWrite tool。
        schedule_callbacks = self._build_schedule_callbacks(project_id=project_id)
        # Cowork host-specific tools — Browser group 只在 Cowork 註冊,SDK 不背
        # playwright dep。`is_browser_available()` 不通過就 skip,LLM 看不到。
        from orion_cowork_sidecar.browser_tools import (
            build_browser_tools,
            is_browser_available,
        )
        host_tools: list[Any] = [
            OpenUrlTool(),
            OpenPathTool(),
            # Plan Mode tools— SDK 自動透過 plan_mode_aware
            # wrapper enforce read-only 白名單。Host 不用包 policy。
            EnterPlanModeTool(),
            ExitPlanModeTool(),
        ]
        # Multi-pane collaboration— 若此 session 已綁進 collab,
        # 注入 AskPaneTool 讓 LLM 可跨 pane query。
        collab_roster_lines: list[str] = []
        role_prompt_addendum: str | None = None
        if session_id is not None:
            coll_id, my_pane_name, my_pane_role = await storage.get_collaboration_for_session(
                engine, session_id,
            )
            if coll_id is not None:
                from orion_sdk.tools.special import AskPaneTool

                ask_pane_cb = self._build_ask_pane_callback(coll_id, engine)
                host_tools.append(AskPaneTool(callback=ask_pane_cb))
                # System prompt 帶 collaboration roster — LLM 才知道自己是誰、旁邊有誰
                panes = await storage.list_collaboration_panes(engine, coll_id)
                others = [p for p in panes if p.session_id != session_id]
                you_role = my_pane_role or "agent"
                collab_roster_lines.append(
                    f"You are pane `@{my_pane_name or 'unnamed'}` (role: {you_role}) "
                    f"in a multi-pane collaboration. Other panes you can query via "
                    f"the AskPane tool:"
                )
                if others:
                    for p in others:
                        role_str = p.pane_role or "agent"
                        collab_roster_lines.append(
                            f"  - `@{p.pane_name}` (role: {role_str})"
                        )
                else:
                    collab_roster_lines.append(
                        "  (no other panes yet — you are working solo for now)"
                    )
                collab_roster_lines.append(
                    "Use AskPane to read what other panes have done. Their output "
                    "is non-blocking — if they are still running, you'll get partial "
                    "output + status='running'; decide whether to proceed with partial "
                    "info, suggest the user wait, or work on something else."
                )
                # 載入 role markdown(bundled + user override)→ 套 disabled_tools +
                # 取 prompt body 等下 append 到 system_prompt。
                # User 可在 Settings 對個別 role 關掉(disabled_roles pref,CSV)—
                # 該 role 仍存在當 label,但不再套 prompt / disabled_tools。
                disabled_roles_raw = await storage.get_pref(engine, "disabled_roles") or ""
                disabled_roles = {r.strip() for r in disabled_roles_raw.split(",") if r.strip()}
                if (
                    my_pane_role
                    and my_pane_role not in ("custom", "")
                    and my_pane_role not in disabled_roles
                ):
                    try:
                        from orion_sdk.roles import load_all_roles
                        roles = load_all_roles(user_id=storage.LOCAL_USER_ID)
                        by_name = {r.name: r for r in roles}
                        role_obj = by_name.get(my_pane_role)
                        if role_obj is not None:
                            # Merge role 預設關掉的 tools 進當前 disabled_set
                            for t in role_obj.default_disabled_tools:
                                disabled_set.add(t)
                            if role_obj.body and role_obj.body.strip():
                                role_prompt_addendum = role_obj.body.strip()
                    except Exception as e: # noqa: BLE001
                        print(
                            f"[role] load {my_pane_role!r} failed: {e}",
                            file=__import__('sys').stderr, flush=True,
                        )
        if is_browser_available():
            host_tools.extend(build_browser_tools()) # type: ignore[arg-type]
        tools = (
            build_default_tool_set(
                asker=None,
                disabled_tools=disabled_set,
                schedule_callbacks=schedule_callbacks,
                extra_tools=host_tools,
            )
            + mcp.tools
        )
        # AgentTool— spawn 子 agent 跑 self-contained 任務。
        # child_tools 是當前已 build 的全套 tools(AgentTool 自身會過濾掉自己,
        # 防止 sub-agent 再 spawn sub-agent;sub_agent_depth >= 1 也有守)。
        # 預設 disabled(在 cowork_prefs.disabled_tools 內由 init_storage 一次性
        # seed),user 在 Settings → 工具 自己開,避免 LLM 任意 spawn 推高 cost。
        if "Agent" not in disabled_set:
            tools.append(AgentTool(provider=llm, child_tools=list(tools), max_child_turns=10))

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
        # B4:project instructions file 優先 — user 直接編 `<ws>/.orion/
        # instructions.md` 不用過 RPC,read 時拿 file content。
        if effective_workspace:
            from pathlib import Path as _Path
            inst_file = _Path(effective_workspace) / ".orion" / "instructions.md"
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
        if role_prompt_addendum:
            system_prompt += "\n\n# Your role\n\n" + role_prompt_addendum
        if collab_roster_lines:
            system_prompt += (
                "\n\n# Multi-pane collaboration\n\n"
                + "\n".join(collab_roster_lines)
            )

        include_ws = bool(effective_workspace)
        # Project chat → auto-extract 寫 <workspace>/.orion/memory/
        # 沒 project → 寫 user-level(SDK default)
        memory_override: Path | None = None
        if project_id and effective_workspace:
            memory_override = Path(effective_workspace) / ".orion" / "memory"
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
        # Hydrate cumulative token stats from DB(cross-restart cost 才不歸 0)
        try:
            persisted = await storage.get_session_stats(engine, sid)
            conv.stats.input_tokens = persisted["input_tokens"]
            conv.stats.output_tokens = persisted["output_tokens"]
            conv.stats.cache_read_tokens = persisted["cache_read_tokens"]
            conv.stats.cache_creation_tokens = persisted["cache_creation_tokens"]
            conv.stats.turns = persisted["turns"]
        except Exception as e: # noqa: BLE001
            print(
                f"[stats] hydrate failed for {sid[:8]}: {e}",
                file=__import__('sys').stderr, flush=True,
            )
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
        scheduled_map = await storage.list_session_scheduled_by_map(engine)
        starred_ids = await storage.list_session_starred_ids(engine)
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
                        "starred": r.session_id in starred_ids,
                        "scheduled_by": (
                            {
                                "schedule_id": scheduled_map[r.session_id]["id"],
                                "schedule_name": scheduled_map[r.session_id]["name"],
                            }
                            if r.session_id in scheduled_map
                            else None
                        ),
                        "forked_from_session_id": r.forked_from_session_id,
                        "forked_from_message_index": r.forked_from_message_index,
                    }
                    for r in rows
                ],
            },
            "final": True,
        }

    async def conversation_rename(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        title = params.get("title")
        if not isinstance(sid, str) or not isinstance(title, str) or not title.strip():
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "session_id and non-empty title required"},
                   "final": True}
            return
        engine = await self.ensure_engine()
        ok = await storage.rename_session(engine, sid, title)
        if not ok:
            yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
            return
        # title 改了 → 既有快取 conv 不必清(title 只在 metadata 表),但
        # 把 _title_done 移除以防 auto-fill 行為被誤觸發
        self._title_done.discard(sid)
        yield {"event": "conversation_renamed",
               "data": {"session_id": sid, "title": title.strip()},
               "final": True}

    async def conversation_set_starred(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        starred = params.get("starred")
        if not isinstance(sid, str) or not isinstance(starred, bool):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                   "message": "session_id and starred(bool) required"},
                   "final": True}
            return
        engine = await self.ensure_engine()
        await storage.set_session_starred(engine, sid, starred)
        yield {"event": "conversation_starred_set",
               "data": {"session_id": sid, "starred": starred},
               "final": True}

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
                "collaboration_id": ext["collaboration_id"],
                "pane_name": ext["pane_name"],
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

    # ─── Collaboration (multi-pane) ─────────────────────────────────────

    @staticmethod
    def _collab_to_dict(c: "storage.Collaboration") -> dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "workspace_dir": c.workspace_dir,
            "project_id": c.project_id,
            "budget_usd_cap": c.budget_usd_cap,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }

    @staticmethod
    def _pane_to_dict(p: "storage.CollaborationPane") -> dict[str, Any]:
        return {
            "session_id": p.session_id,
            "collaboration_id": p.collaboration_id,
            "pane_name": p.pane_name,
            "pane_role": p.pane_role,
            "pane_position": p.pane_position,
        }

    async def collaboration_create(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                "message": "name required"}, "final": True}
            return
        workspace_dir = params.get("workspace_dir")
        project_id = params.get("project_id")
        budget_usd_cap = params.get("budget_usd_cap")
        engine = await self.ensure_engine()
        coll = await storage.create_collaboration(
            engine,
            name=name.strip()[:100],
            workspace_dir=workspace_dir if isinstance(workspace_dir, str) else None,
            project_id=project_id if isinstance(project_id, str) else None,
            budget_usd_cap=float(budget_usd_cap) if isinstance(budget_usd_cap, (int, float)) else None,
        )
        yield {
            "event": "collaboration_created",
            "data": {"collaboration": self._collab_to_dict(coll), "panes": []},
            "final": True,
        }

    async def collaboration_list(
        self, _params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        engine = await self.ensure_engine()
        colls = await storage.list_collaborations(engine)
        # 同時帶各 collab 的 panes 簡略表(只 pane_name + role + session_id,layout 細節留給 get)
        all_data: list[dict[str, Any]] = []
        for c in colls:
            panes = await storage.list_collaboration_panes(engine, c.id)
            all_data.append({
                "collaboration": self._collab_to_dict(c),
                "panes": [self._pane_to_dict(p) for p in panes],
            })
        yield {
            "event": "collaboration_list",
            "data": {"items": all_data},
            "final": True,
        }

    async def collaboration_get(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        cid = params.get("collaboration_id")
        if not isinstance(cid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        coll = await storage.get_collaboration(engine, cid)
        if coll is None:
            yield {"event": "error", "data": {"code": "NOT_FOUND"}, "final": True}
            return
        panes = await storage.list_collaboration_panes(engine, cid)
        yield {
            "event": "collaboration_get",
            "data": {
                "collaboration": self._collab_to_dict(coll),
                "panes": [self._pane_to_dict(p) for p in panes],
            },
            "final": True,
        }

    async def collaboration_delete(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        cid = params.get("collaboration_id")
        if not isinstance(cid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        # delete_sessions=True 把成員 session 一起整批 delete(對話也消失)
        # =False(預設)只刪 collab 容器,session 釋放成個人對話
        delete_sessions = bool(params.get("delete_sessions"))
        engine = await self.ensure_engine()
        deleted_session_ids: list[str] = []
        if delete_sessions:
            # 先抓 pane session_id 再做 delete(delete_collaboration 會把
            # collaboration_id NULL 掉,之後查不到)
            panes = await storage.list_collaboration_panes(engine, cid)
            deleted_session_ids = [p.session_id for p in panes]
        ok = await storage.delete_collaboration(engine, cid)
        # 釋放對應 conv:它們可能 cache 在 _conversations,內注入過 AskPaneTool callback
        for sid in list(self._conversations.keys()):
            cur_cid, _, _ = await storage.get_collaboration_for_session(engine, sid)
            if cur_cid is None:
                self._conversations.pop(sid, None)
        # 若選擇連 session 一起刪 — 走 delete_session 標準路徑(會清 messages /
        # ext / blobs 等)
        if delete_sessions and deleted_session_ids:
            for sid in deleted_session_ids:
                try:
                    await storage.delete_session(engine, sid)
                except Exception as e: # noqa: BLE001
                    print(
                        f"[collab.delete] failed to delete session {sid[:8]}: {e}",
                        file=__import__('sys').stderr, flush=True,
                    )
                self._conversations.pop(sid, None)
        yield {
            "event": "collaboration_deleted",
            "data": {
                "collaboration_id": cid,
                "ok": ok,
                "deleted_session_count": len(deleted_session_ids) if delete_sessions else 0,
            },
            "final": True,
        }

    async def collaboration_add_pane(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        cid = params.get("collaboration_id")
        sid = params.get("session_id")
        pane_name = params.get("pane_name")
        if not (
            isinstance(cid, str)
            and isinstance(sid, str)
            and isinstance(pane_name, str)
            and pane_name.strip()
        ):
            yield {"event": "error", "data": {"code": "BAD_PARAMS",
                "message": "collaboration_id, session_id, pane_name required"}, "final": True}
            return
        engine = await self.ensure_engine()
        coll = await storage.get_collaboration(engine, cid)
        if coll is None:
            yield {"event": "error", "data": {"code": "NOT_FOUND",
                "message": "collaboration not found"}, "final": True}
            return
        # Dedupe by pane_name within collab
        existing = await storage.find_collaboration_pane(engine, cid, pane_name.strip())
        if existing is not None and existing.session_id != sid:
            yield {"event": "error", "data": {"code": "CONFLICT",
                "message": f"pane name '{pane_name}' already in use"}, "final": True}
            return
        pane_role = params.get("pane_role")
        pane_position = params.get("pane_position")
        await storage.add_pane_to_collaboration(
            engine,
            collaboration_id=cid,
            session_id=sid,
            pane_name=pane_name.strip()[:128],
            pane_role=pane_role if isinstance(pane_role, str) else None,
            pane_position=pane_position if isinstance(pane_position, dict) else None,
        )
        # Invalidate cached conv — 下次 send 重 build,會帶 AskPaneTool
        self._conversations.pop(sid, None)
        yield {
            "event": "pane_added",
            "data": {
                "collaboration_id": cid,
                "session_id": sid,
                "pane_name": pane_name.strip()[:128],
                "pane_role": pane_role if isinstance(pane_role, str) else None,
                "pane_position": pane_position if isinstance(pane_position, dict) else None,
            },
            "final": True,
        }

    async def collaboration_remove_pane(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        if not isinstance(sid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        old_cid = await storage.remove_pane_from_collaboration(engine, sid)
        # Invalidate cached conv — 下次 send 重 build,沒有 AskPaneTool 了
        self._conversations.pop(sid, None)
        yield {
            "event": "pane_removed",
            "data": {"session_id": sid, "collaboration_id": old_cid},
            "final": True,
        }

    async def collaboration_update_pane_position(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        sid = params.get("session_id")
        pane_position = params.get("pane_position")
        if not isinstance(sid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        ok = await storage.update_pane_position(
            engine, sid,
            pane_position if isinstance(pane_position, dict) else None,
        )
        yield {
            "event": "pane_position_updated",
            "data": {"session_id": sid, "ok": ok},
            "final": True,
        }

    async def collaboration_cost_summary(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        cid = params.get("collaboration_id")
        if not isinstance(cid, str):
            yield {"event": "error", "data": {"code": "BAD_PARAMS"}, "final": True}
            return
        engine = await self.ensure_engine()
        # SDK sessions table 的 input_tokens / output_tokens 從未被 update —
        # 真實 token 計數活在 live `conv.stats` 上(in-memory)。所以我們:
        #   1. 從 storage 拿 panes 結構 + provider/model(no tokens)
        #   2. 對每 pane 取 in-memory conv;沒在記憶體就 resume
        #   3. 從 conv.stats 拿 cumulative input/output/cache_read/cache_creation
        #   4. 用 orion_model.pricing.get_pricing(有 unknown-model fallback)算 USD
        from orion_model.pricing import get_pricing

        panes = await storage.list_collaboration_panes(engine, cid)
        out_panes: list[dict[str, Any]] = []
        total_in = 0
        total_out = 0
        total_usd = 0.0
        for p in panes:
            sid = p.session_id
            conv = self._conversations.get(sid)
            if conv is None:
                # Resume from DB so we get conv.stats — Conversation.__init__ 不會
                # 自動 hydrate stats(stats 是 forward-only accumulator),但 provider /
                # model 至少能拿到當前 metadata 顯給 user。
                conv = await self._resume_from_db(sid, engine)
                if conv is not None:
                    self._conversations[sid] = conv
            provider = conv.provider.name if conv else None
            model = conv.provider.model if conv else None
            stats = getattr(conv, "stats", None) if conv else None
            in_t = getattr(stats, "input_tokens", 0) if stats else 0
            out_t = getattr(stats, "output_tokens", 0) if stats else 0
            cr_t = getattr(stats, "cache_read_tokens", 0) if stats else 0
            cc_t = getattr(stats, "cache_creation_tokens", 0) if stats else 0
            n_turns = getattr(stats, "turns", 0) if stats else 0
            cost_usd = 0.0
            if provider and model:
                pricing = get_pricing(provider, model)
                in_price = pricing.get("input", 0.0)
                out_price = pricing.get("output", 0.0)
                cr_price = pricing.get("cache_read", in_price)
                cc_price = pricing.get("cache_creation", in_price)
                cost_usd = round(
                    (in_t * in_price + out_t * out_price
                     + cr_t * cr_price + cc_t * cc_price) / 1_000_000,
                    6,
                )
            total_in += in_t
            total_out += out_t
            total_usd += cost_usd
            out_panes.append({
                "session_id": sid,
                "pane_name": p.pane_name,
                "pane_role": p.pane_role,
                "pane_position": p.pane_position,
                "model": model,
                "provider": provider,
                "input_tokens": in_t,
                "output_tokens": out_t,
                "cache_read_tokens": cr_t,
                "cache_creation_tokens": cc_t,
                "n_turns": n_turns,
                "n_messages": 0, # 維持既有 API shape
                "cost_usd": cost_usd,
            })
        yield {
            "event": "collaboration_cost_summary",
            "data": {
                "total_panes": len(panes),
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_cost_usd": round(total_usd, 6),
                "panes": out_panes,
            },
            "final": True,
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

    async def conversation_delete_many(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Bulk delete:對每個 sid 跑 cascade delete(含 fork 子孫 + Loop 排程)。

        傳入 session_ids 內非 str / 非 valid uuid / 重複 都會被略過,不會炸。
        """
        raw_ids = params.get("session_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_ids required"},
                "final": True,
            }
            return
        valid: list[str] = []
        seen: set[str] = set()
        for x in raw_ids:
            if not isinstance(x, str) or x in seen:
                continue
            try:
                UUID(x)
            except (ValueError, TypeError):
                continue
            seen.add(x)
            valid.append(x)
        if not valid:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "no valid session_ids"},
                "final": True,
            }
            return

        engine = await self.ensure_engine()
        # Abort in-flight + 清 in-memory cache
        for sid in valid:
            ctx = self._aborts.get(sid)
            if ctx is not None:
                ctx.abort_event.set()
            self._conversations.pop(sid, None)
            self._aborts.pop(sid, None)
            self._title_done.discard(sid)

        stats = await storage.delete_many_sessions(engine, valid)
        yield {
            "event": "conversation_deleted_many",
            "data": stats,
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
            target = Path(proj.workspace_dir) / ".orion" / "mcp.json"
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
            target = Path(proj.workspace_dir) / ".orion" / "mcp.json"
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
            target = Path(proj.workspace_dir) / ".orion" / "mcp.json"
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
        except Exception as e: # noqa: BLE001
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
                except Exception: # noqa: BLE001
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
                except Exception: # noqa: BLE001
                    pass

    async def conversation_fork(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """從某 turn(含)分叉出新 session,原 session 完全不動。

        Params:
          source_session_id: 必填
          up_to_message_index: 必填,raw chronological row index(inclusive)
          title (optional): 新 session 的 title;沒給用「<source title> (fork)」

        Source session messages [0..up_to_message_index] copy 進新 session,
        workspace_dir / project_id 繼承,budget / plan state 不繼承。返回
        新 session_id。
        """
        src_sid = params.get("source_session_id")
        up_to = params.get("up_to_message_index")
        title = params.get("title")
        if not isinstance(src_sid, str) or not src_sid or not isinstance(up_to, int):
            yield {
                "event": "error",
                "data": {
                    "code": "BAD_PARAMS",
                    "message": "source_session_id + up_to_message_index required",
                },
                "final": True,
            }
            return
        try:
            UUID(src_sid)
        except (ValueError, TypeError):
            yield {
                "event": "error",
                "data": {"code": "BAD_SESSION_ID", "message": f"invalid UUID: {src_sid!r}"},
                "final": True,
            }
            return
        if title is not None and not isinstance(title, str):
            title = None

        engine = await self.ensure_engine()
        try:
            new_sid = await storage.fork_session(
                engine,
                source_session_id=src_sid,
                up_to_message_index=up_to,
                title=title,
            )
        except ValueError as e:
            yield {
                "event": "error",
                "data": {"code": "FORK_FAILED", "message": str(e)},
                "final": True,
            }
            return
        except Exception as e: # noqa: BLE001
            yield {
                "event": "error",
                "data": {"code": "FORK_FAILED", "message": f"{type(e).__name__}: {e}"},
                "final": True,
            }
            return

        # In-memory cache 不需要先 build — 下次 conversation.send 走 lazy resume
        # 路徑會自動從 DB load 進來,跟一般 session 一樣。
        yield {
            "event": "conversation_forked",
            "data": {
                "session_id": new_sid,
                "source_session_id": src_sid,
                "forked_from_message_index": up_to,
            },
            "final": True,
        }

    async def conversation_count_fork_descendants(
        self, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """回 session 的 fork 子孫數 — Sidebar delete confirm 用。"""
        sid = params.get("session_id")
        if not isinstance(sid, str) or not sid:
            yield {
                "event": "error",
                "data": {"code": "BAD_PARAMS", "message": "session_id required"},
                "final": True,
            }
            return
        engine = await self.ensure_engine()
        count = await storage.count_fork_descendants(engine, sid)
        yield {
            "event": "fork_descendants_count",
            "data": {"session_id": sid, "count": count},
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

        簡化版:從最後一個 user msg 的 text 重 send。把那個 user
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
                except Exception: # noqa: BLE001
                    pass


def _compute_cumulative_cost(conv: Any) -> float:
    """跟 conversation_stats 同一套算法 — 把 stats × pricing → USD。

    conv 為 None 或還沒跑過 turn → 0.0。Unknown provider/model 走 pricing
    fallback,絕不丟例外(budget check 不該炸 user)。
    """
    if conv is None:
        return 0.0
    try:
        from orion_model.pricing import get_pricing
        s = conv.stats
        provider = conv.provider.name
        model = conv.provider.model
        p = get_pricing(provider, model)
        input_price = p.get("input", 0.0)
        output_price = p.get("output", 0.0)
        cache_read_price = p.get("cache_read", input_price)
        cache_creation_price = p.get("cache_creation", input_price)
        return round(
            (
                s.input_tokens * input_price
                + s.output_tokens * output_price
                + s.cache_read_tokens * cache_read_price
                + s.cache_creation_tokens * cache_creation_price
            )
            / 1_000_000,
            6,
        )
    except Exception: # noqa: BLE001
        return 0.0


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
    except Exception as e: # noqa: BLE001
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
                break # 進入下個 turn
            if r2 == "user" and _is_user_prompt_row(cj2):
                break # 進入下個 turn
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

    慢載入修:attachment 不 inline base64,只送 ref
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
            continue # 跳過純 tool_use / tool_result 訊息
        out.append({
            "role": role,
            "text": text,
            "attachments": attachments,
            # message_index 給 renderer 之後 lazy fetch 用 (跟 ref.message_index 一致)
            "message_index": msg_idx,
        })
    return out
