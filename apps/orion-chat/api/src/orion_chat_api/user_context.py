"""Soul(永久人格)讀寫 + 對話的 per-user system prompt 前綴。

Soul 存 `~/.orion/users/<uid>/memory/soul.md`(沿用 memory layout,跨 host 共用)。
它**不走 memory ranker** — 每次新對話固定 inject 進 system prompt 前綴,
讓模型把 user 當成認識的人。對齊 Cowork 的 soul 注入(handlers `_build_conversation`)。

注入點是 Conversation 建構時(`system_prompt` 會被 prepend 到完整 system prompt,
見 conversation.py send()),所以 soul 變更在下一個 session / cache-miss rebuild 才生效 —
與 Cowork 相同語意。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_sdk.memory.paths import user_memory_paths
from orion_sdk.storage.db.engine import db_session
from orion_sdk.storage.db.models import Project

# 第一人稱框架 — 對齊 Cowork handlers.py 的 soul 注入文案。
_SOUL_FRAMING = (
    "# What you remember about this person\n\n"
    "(This is your own first-person reflection from past conversations. "
    "Speak to them naturally, the way you'd speak to someone you know.)\n\n"
)


def soul_path(user_id: str) -> Path:
    """Soul markdown 檔位置:`~/.orion/users/<uid>/memory/soul.md`。"""
    return user_memory_paths(user_id).memory_dir / "soul.md"


def read_soul(user_id: str) -> str:
    """讀 soul.md。不存在 / 讀失敗回空字串。"""
    p = soul_path(user_id)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except OSError:
        return ""


def write_soul(content: str, user_id: str) -> None:
    """寫 soul.md。空內容 = 刪檔(重置)。"""
    p = soul_path(user_id)
    if not content.strip():
        if p.exists():
            p.unlink()
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip() + "\n", encoding="utf-8")


def build_user_system_prefix(user_id: str) -> str:
    """組該 user 的 system prompt 前綴(目前 = soul)。沒內容回空字串。

    Conversation.system_prompt 不為空時會被 prepend 到完整 system prompt,
    所以回空字串時等同沒注入(不影響原本的靜態 + 動態段)。
    """
    soul = read_soul(user_id).strip()
    if not soul:
        return ""
    return _SOUL_FRAMING + soul


def _role_body(user_id: str, role_name: str) -> str:
    """讀 active role 的 ROLE.md body(用 SDK roles loader,per-user)。找不到回空。"""
    from orion_sdk.roles.loader import load_all_roles

    for r in load_all_roles(user_id=user_id):
        if r.name == role_name:
            return (r.body or "").strip()
    return ""


async def _project_instructions(
    engine: AsyncEngine, project_id: str, user_id: str,
) -> str:
    """讀 project.custom_instructions(驗 ownership)。找不到回空。"""
    async with db_session(engine) as db:
        row = (
            await db.execute(
                select(Project).where(
                    Project.id == project_id, Project.user_id == user_id,
                ),
            )
        ).scalar_one_or_none()
    return (row.custom_instructions or "").strip() if row else ""


async def build_session_system_prefix(
    engine: AsyncEngine, user_id: str, session_id: str,
) -> str:
    """組 per-session system prompt 前綴 = soul + active role + project 指令。

    每個 turn 開始時重算(見 chat.py runner),所以改 role / project 下一輪即生效,
    不必 evict cache。對齊 Cowork `_build_conversation` 的注入順序。
    """
    from orion_chat_api.conversation_meta import fetch_session_context

    parts: list[str] = []
    soul = read_soul(user_id).strip()
    if soul:
        parts.append(_SOUL_FRAMING + soul)

    project_id, active_role = await fetch_session_context(engine, str(session_id))
    if active_role:
        body = _role_body(user_id, active_role)
        if body:
            parts.append("# Your role\n\n" + body)
    if project_id:
        instr = await _project_instructions(engine, project_id, user_id)
        if instr:
            parts.append("# Project instructions\n\n" + instr)
    return "\n\n".join(parts)


def project_workspace_dir(user_id: str, project_id: str) -> Path:
    """Project 的共享 workspace(sandbox 在 user 命名空間下,非 user 任意路徑)。

    multi-tenant:**不**用 project.workspace_dir 那個自由欄位當 cwd(Bash 會逃逸),
    一律落 `~/.orion/users/<uid>/projects/<pid>/workspace/`,同 project 的 session 共享。
    """
    safe_pid = project_id.replace("/", "_").replace("\\", "_").lstrip(".")
    return (
        user_memory_paths(user_id).root / "projects" / safe_pid / "workspace"
    )
