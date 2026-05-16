"""Cowork local SQLite persistence(Phase 31-D)。

跟 chat-api 的 DbSessionManager 不同:
- Single-user 模式 — 用固定 dummy user "cowork-local"
- 不依賴 fastapi / jwt(只用 orion-sdk storage primitives)
- DB 位置:`~/.orion-cowork/sessions.db`(macOS / Linux),
            `%LOCALAPPDATA%\\Orion Cowork\\sessions.db`(Windows),
            `$ORION_COWORK_DATA_DIR/sessions.db`(e2e 用)

Public API:
    init_storage() -> engine                   # call once at startup
    save_session_metadata(engine, sid, ...)
    update_title_if_empty(engine, sid, title)
    list_sessions(engine) -> list[SessionMeta]
    delete_session(engine, sid)
    append_messages(engine, sid, messages)
    load_messages(engine, sid) -> list[NormalizedMessage]
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orion_model.types import NormalizedMessage
from orion_sdk.storage.db.engine import create_db_engine, db_session, init_db
from orion_sdk.storage.db.models import ConversationMetadata as MetaRow
from orion_sdk.storage.db.models import Message as MessageRow
from orion_sdk.storage.db.models import Session as SessionRow
from orion_sdk.storage.db.models import User as UserRow
from orion_sdk.storage.resume import _message_from_dict as _msg_from_dict

from orion_cowork_sidecar.blob_store import BlobStore

LOCAL_USER_ID = "cowork-local"
LOCAL_USERNAME = "local"


def data_dir() -> Path:
    """Cowork user data root,可由 ORION_COWORK_DATA_DIR env 覆蓋。"""
    env = os.environ.get("ORION_COWORK_DATA_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Orion Cowork"
    return Path.home() / ".orion-cowork"


def _db_url() -> str:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{d / 'sessions.db'}"


def get_blob_store() -> BlobStore:
    """Singleton blob store(同 data_dir 下的 blobs/)。"""
    return BlobStore(data_dir() / "blobs")


def _persist_image_blocks(content_value: Any, blob: BlobStore) -> Any:
    """寫前處理:list 內 image dict 的 inline base64 data 抽 blob,改成 ref。

    Input:  list[dict],dict 可能含 {type: "image", media_type, data: base64-str}
    Output: 同 list,但 image dict 換成 {type: "image", media_type, blob_id}
    其他 block 原樣保留。已經是 ref 形式(無 data 有 blob_id)的也原樣。
    """
    if not isinstance(content_value, list):
        return content_value
    out = []
    for b in content_value:
        if (
            isinstance(b, dict)
            and b.get("type") == "image"
            and isinstance(b.get("data"), str)
            and b["data"]
        ):
            try:
                raw = base64.b64decode(b["data"])
                blob_id = blob.put(raw)
                out.append({
                    "type": "image",
                    "media_type": b.get("media_type") or "image/png",
                    "blob_id": blob_id,
                })
                continue
            except Exception:  # noqa: BLE001
                # base64 decode 壞了,保留原樣不要丟資料
                pass
        out.append(b)
    return out


def _hydrate_image_blocks(content_json: Any, blob: BlobStore) -> Any:
    """讀後處理:image ref(blob_id)→ 重建 inline data(base64)供 LLM 使用。

    Legacy inline base64 直接原樣回(向後相容,既有 session 不會壞)。
    blob 檔不見的話,丟掉那個 image block,其他不動。
    """
    if not isinstance(content_json, list):
        return content_json
    out = []
    for b in content_json:
        if (
            isinstance(b, dict)
            and b.get("type") == "image"
            and "blob_id" in b
            and "data" not in b
        ):
            try:
                raw = blob.get(b["blob_id"])
                out.append({
                    "type": "image",
                    "media_type": b.get("media_type") or "image/png",
                    "data": base64.b64encode(raw).decode("ascii"),
                })
                continue
            except FileNotFoundError:
                # 孤兒 ref,跳過(避免炸 LLM send)
                continue
        out.append(b)
    return out


async def init_storage() -> AsyncEngine:
    """Init engine + migrations + dummy user + cowork-only 擴充表。Idempotent。"""
    engine = create_db_engine(_db_url())
    await init_db(engine)
    await _upsert_local_user(engine)
    await _ensure_cowork_ext_tables(engine)
    await _ensure_default_workspace(engine)
    return engine


async def _ensure_default_workspace(engine: AsyncEngine) -> None:
    """個人對話的 default workspace:`<data_dir>/users/<uid>/workspace/`。

    第一次啟動建目錄並寫進 prefs(若 user 還沒手動設過),之後 user 在
    Settings 改了 prefs 我們不覆蓋。
    """
    default_ws = data_dir() / "users" / LOCAL_USER_ID / "workspace"
    try:
        default_ws.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    existing = await get_pref(engine, "default_workspace_dir")
    if not existing:
        await set_pref(engine, "default_workspace_dir", str(default_ws))


async def _ensure_cowork_ext_tables(engine: AsyncEngine) -> None:
    """Cowork 專屬擴充表(不動 SDK schema):
       - cowork_session_ext:per-session workspace_dir(override) + project_id
       - cowork_projects:Project 定義
       - cowork_prefs:KV(default_workspace_dir 等 app 級偏好)
    """
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS cowork_session_ext (
                session_id TEXT PRIMARY KEY,
                workspace_dir TEXT,
                project_id TEXT
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS cowork_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                workspace_dir TEXT,
                custom_instructions TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        await conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS cowork_prefs (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        await conn.commit()


async def get_pref(engine: AsyncEngine, key: str) -> str | None:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT value FROM cowork_prefs WHERE key = ?", (key,),
        )
        row = result.first()
    return row[0] if row else None


async def set_pref(engine: AsyncEngine, key: str, value: str | None) -> None:
    """value=None → 刪除該 key。"""
    async with engine.connect() as conn:
        if value is None:
            await conn.exec_driver_sql(
                "DELETE FROM cowork_prefs WHERE key = ?", (key,),
            )
        else:
            await conn.exec_driver_sql(
                """
                INSERT INTO cowork_prefs (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
        await conn.commit()


async def list_prefs(engine: AsyncEngine) -> dict[str, str]:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql("SELECT key, value FROM cowork_prefs")
        return {row[0]: row[1] for row in result.all()}


async def _upsert_local_user(engine: AsyncEngine) -> None:
    async with db_session(engine) as s:
        existing = await s.get(UserRow, LOCAL_USER_ID)
        if existing is None:
            s.add(UserRow(
                id=LOCAL_USER_ID,
                username=LOCAL_USERNAME,
                password_hash="$2b$12$cowork.local.no.password.................",
            ))
            await s.commit()


@dataclass
class SessionMeta:
    session_id: str
    provider: str
    model: str
    title: str | None
    created_at: float
    n_messages: int


async def save_session_metadata(
    engine: AsyncEngine,
    session_id: str,
    *,
    provider: str,
    model: str,
) -> None:
    """Insert SessionRow + empty ConversationMetadata(idempotent)。"""
    async with db_session(engine) as s:
        row = await s.get(SessionRow, session_id)
        if row is None:
            s.add(SessionRow(
                id=session_id,
                user_id=LOCAL_USER_ID,
                provider=provider,
                model=model,
            ))
        else:
            row.provider = provider
            row.model = model

        meta = await s.get(MetaRow, session_id)
        if meta is None:
            s.add(MetaRow(session_id=session_id))
        await s.commit()


async def update_title_if_empty(engine: AsyncEngine, session_id: str, title: str) -> None:
    async with db_session(engine) as s:
        meta = await s.get(MetaRow, session_id)
        if meta is None:
            return
        if meta.title:
            return
        meta.title = title[:60].strip()
        await s.commit()


async def list_sessions(engine: AsyncEngine) -> list[SessionMeta]:
    async with db_session(engine) as s:
        stmt = (
            select(SessionRow)
            .where(SessionRow.user_id == LOCAL_USER_ID)
            .order_by(SessionRow.created_at.desc())
        )
        rows = list((await s.execute(stmt)).scalars())

        out: list[SessionMeta] = []
        for r in rows:
            meta = await s.get(MetaRow, r.id)
            title = meta.title if meta is not None else None
            count_stmt = select(MessageRow.id).where(MessageRow.session_id == r.id)
            n = len(list((await s.execute(count_stmt)).scalars()))
            out.append(SessionMeta(
                session_id=r.id,
                provider=r.provider or "anthropic",
                model=r.model or "claude-sonnet-4-6",
                title=title,
                created_at=r.created_at.timestamp() if r.created_at else time.time(),
                n_messages=n,
            ))
        return out


async def delete_session(engine: AsyncEngine, session_id: str) -> bool:
    """Cascade delete:DB rows + 該 session 的 blob 檔。

    先撈 content_json 內所有 blob_id 收集,DB rows commit 後再 unlink blob 檔
    (中途 unlink fail 不影響 DB consistency,下次 cleanup_orphan_blobs 會撿)。
    """
    async with db_session(engine) as s:
        row = await s.get(SessionRow, session_id)
        if row is None:
            return False
        # 先撈 messages 內所有 blob_id ref
        msg_rows = await s.execute(
            select(MessageRow.content_json).where(MessageRow.session_id == session_id)
        )
        blob_ids = _collect_blob_ids([cj for (cj,) in msg_rows])
        # Explicit cascade(避免 SQLite FK 設定差異 — CASCADE 也設了 ondelete)
        await s.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
        await s.execute(delete(MetaRow).where(MetaRow.session_id == session_id))
        await s.delete(row)
        await s.commit()
    # DB 已 commit;unlink blob 檔。fail 不影響 DB,下次 cleanup 會撿。
    blob = get_blob_store()
    for bid in blob_ids:
        try:
            blob.delete(bid)
        except Exception:  # noqa: BLE001
            pass
    return True


def _collect_blob_ids(content_jsons: list[Any]) -> list[str]:
    """從多個 content_json list 內抽出所有 image block 的 blob_id。"""
    out: list[str] = []
    for cj in content_jsons:
        if not isinstance(cj, list):
            continue
        for b in cj:
            if (
                isinstance(b, dict)
                and b.get("type") == "image"
                and isinstance(b.get("blob_id"), str)
            ):
                out.append(b["blob_id"])
    return out


async def cleanup_orphan_blobs(engine: AsyncEngine) -> dict[str, int]:
    """Scan messages 撈所有被 ref 的 blob_id;blobs/ 內沒在這集合的就 unlink。

    safety net — 若 delete_session 過程 unlink 失敗,或 migration / 異常產生
    孤兒 blob,這裡會撿。idempotent。
    """
    referenced: set[str] = set()
    async with db_session(engine) as s:
        rows = await s.execute(select(MessageRow.content_json))
        for (cj,) in rows:
            referenced.update(_collect_blob_ids([cj]))
    blob = get_blob_store()
    deleted = 0
    bytes_freed = 0
    for path in blob.root.glob("*.bin"):
        bid = path.stem
        if bid in referenced:
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            deleted += 1
            bytes_freed += size
        except OSError:
            pass
    return {
        "referenced": len(referenced),
        "deleted": deleted,
        "bytes_freed": bytes_freed,
    }


async def get_session_ext(
    engine: AsyncEngine, session_id: str
) -> dict[str, str | None]:
    """讀 cowork_session_ext row。沒 row 回 {workspace_dir: None, project_id: None}。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT workspace_dir, project_id FROM cowork_session_ext WHERE session_id = ?",
            (session_id,),
        )
        row = result.first()
    if row is None:
        return {"workspace_dir": None, "project_id": None}
    return {"workspace_dir": row[0], "project_id": row[1]}


async def set_session_workspace(
    engine: AsyncEngine, session_id: str, workspace_dir: str | None
) -> None:
    """Upsert workspace_dir。None 清空。"""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (session_id, workspace_dir)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET workspace_dir = excluded.workspace_dir
            """,
            (session_id, workspace_dir),
        )
        await conn.commit()


async def set_session_project(
    engine: AsyncEngine, session_id: str, project_id: str | None
) -> None:
    """Upsert project_id。None 清空。"""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (session_id, project_id)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET project_id = excluded.project_id
            """,
            (session_id, project_id),
        )
        await conn.commit()


async def append_messages(
    engine: AsyncEngine,
    session_id: str,
    messages: list[NormalizedMessage],
) -> None:
    """Append 新訊息(caller 負責不重複)。

    寫前掃 ImageBlock 的 base64 data → 抽 file blob,row 內只留 blob_id ref,
    讓 DB row size 從 MB 降回 bytes。
    """
    if not messages:
        return
    blob = get_blob_store()
    async with db_session(engine) as s:
        for msg in messages:
            content_value: Any
            content = msg.content
            if isinstance(content, str):
                content_value = content
            else:
                content_value = [b.model_dump(mode="json") for b in content]
                content_value = _persist_image_blocks(content_value, blob)
            s.add(MessageRow(
                session_id=session_id,
                role=msg.role,
                content_json=content_value,
            ))
        await s.commit()


async def load_messages(
    engine: AsyncEngine,
    session_id: str,
) -> list[NormalizedMessage]:
    """完整 hydrate(含 ImageBlock data)— 給 LLM resume / regenerate 用。

    UI path 用 load_raw_messages 比較快(不打 file system)。
    """
    blob = get_blob_store()
    async with db_session(engine) as s:
        stmt = (
            select(MessageRow.role, MessageRow.content_json)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        rows = list(await s.execute(stmt))
    out: list[NormalizedMessage] = []
    for role, content_json in rows:
        hydrated = _hydrate_image_blocks(content_json, blob)
        msg = _msg_from_dict({"role": role, "content": hydrated})
        if msg is not None:
            out.append(msg)
    return out


async def load_raw_messages(
    engine: AsyncEngine,
    session_id: str,
) -> list[tuple[str, Any]]:
    """UI lightweight 載入:不 hydrate blob,只回 (role, content_json) 原樣。

    切歷史時不會把 N × MB 的圖讀進記憶體,UI 拿到 ref dict 再 lazy 撈單張。
    """
    async with db_session(engine) as s:
        stmt = (
            select(MessageRow.role, MessageRow.content_json)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        rows = list(await s.execute(stmt))
    return [(role, content_json) for role, content_json in rows]


async def read_attachment_data_url(
    engine: AsyncEngine,
    session_id: str,
    message_index: int,
    attachment_index: int,
) -> str:
    """單張 attachment lazy 載入,回 data URL。

    優先讀 blob ref;legacy inline base64 也支援(向後相容)。
    """
    rows = await load_raw_messages(engine, session_id)
    if message_index < 0 or message_index >= len(rows):
        raise IndexError(f"message_index {message_index} out of range")
    _, content_json = rows[message_index]
    if not isinstance(content_json, list):
        raise ValueError("message has no attachments")
    images = [
        b for b in content_json
        if isinstance(b, dict) and b.get("type") == "image"
    ]
    if attachment_index < 0 or attachment_index >= len(images):
        raise IndexError(f"attachment_index {attachment_index} out of range")
    img = images[attachment_index]
    media_type = img.get("media_type") or "image/png"
    if "blob_id" in img and "data" not in img:
        blob = get_blob_store()
        raw = blob.get(img["blob_id"])
        b64 = base64.b64encode(raw).decode("ascii")
    elif isinstance(img.get("data"), str):
        b64 = img["data"]
    else:
        raise ValueError("image block has neither blob_id nor data")
    return f"data:{media_type};base64,{b64}"


@dataclass
class Project:
    id: str
    name: str
    description: str | None
    workspace_dir: str | None
    custom_instructions: str | None
    created_at: float


async def list_projects(engine: AsyncEngine) -> list[Project]:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT id, name, description, workspace_dir, custom_instructions, "
            "created_at FROM cowork_projects ORDER BY created_at DESC"
        )
        return [
            Project(
                id=r[0], name=r[1], description=r[2], workspace_dir=r[3],
                custom_instructions=r[4], created_at=r[5],
            )
            for r in result.all()
        ]


async def get_project(engine: AsyncEngine, project_id: str) -> Project | None:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT id, name, description, workspace_dir, custom_instructions, "
            "created_at FROM cowork_projects WHERE id = ?",
            (project_id,),
        )
        r = result.first()
    if r is None:
        return None
    return Project(
        id=r[0], name=r[1], description=r[2], workspace_dir=r[3],
        custom_instructions=r[4], created_at=r[5],
    )


async def create_project(
    engine: AsyncEngine,
    *,
    name: str,
    workspace_dir: str,
    description: str | None = None,
    custom_instructions: str | None = None,
) -> Project:
    """Workspace 為必填(B0)。建立後在 <workspace>/.orion-cowork/ 建子目錄,
    custom_instructions 同時寫到 <workspace>/.orion-cowork/instructions.md。
    """
    from uuid import uuid4
    pid = str(uuid4())
    now = time.time()
    # 建 co-located 結構
    ws_path = Path(workspace_dir).expanduser()
    cowork_dir = ws_path / ".orion-cowork"
    cowork_dir.mkdir(parents=True, exist_ok=True)
    (cowork_dir / "skills").mkdir(exist_ok=True)
    (cowork_dir / "memory").mkdir(exist_ok=True)
    if custom_instructions and custom_instructions.strip():
        (cowork_dir / "instructions.md").write_text(custom_instructions, encoding="utf-8")
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            "INSERT INTO cowork_projects (id, name, description, workspace_dir, "
            "custom_instructions, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (pid, name, description, workspace_dir, custom_instructions, now),
        )
        await conn.commit()
    return Project(
        id=pid, name=name, description=description, workspace_dir=workspace_dir,
        custom_instructions=custom_instructions, created_at=now,
    )


async def update_project(
    engine: AsyncEngine,
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    workspace_dir: str | None = None,
    custom_instructions: str | None = None,
) -> bool:
    """部分更新;None 表示「不動」,要清空傳空字串。回 True 若有 row 被改。

    custom_instructions 變更時同步寫到 `<workspace>/.orion-cowork/instructions.md`(B4)。
    """
    fields: list[tuple[str, Any]] = []
    if name is not None:
        fields.append(("name", name))
    if description is not None:
        fields.append(("description", description))
    if workspace_dir is not None:
        fields.append(("workspace_dir", workspace_dir or None))
    if custom_instructions is not None:
        fields.append(("custom_instructions", custom_instructions or None))
    if not fields:
        return False
    set_clause = ", ".join(f"{k} = ?" for k, _ in fields)
    params = [v for _, v in fields] + [project_id]
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            f"UPDATE cowork_projects SET {set_clause} WHERE id = ?",
            tuple(params),
        )
        await conn.commit()
        changed = (result.rowcount or 0) > 0
    # 同步 instructions file(B4)
    if changed and custom_instructions is not None:
        proj = await get_project(engine, project_id)
        if proj is not None and proj.workspace_dir:
            try:
                cowork_dir = Path(proj.workspace_dir) / ".orion-cowork"
                cowork_dir.mkdir(parents=True, exist_ok=True)
                inst = cowork_dir / "instructions.md"
                if custom_instructions:
                    inst.write_text(custom_instructions, encoding="utf-8")
                elif inst.exists():
                    inst.unlink()
            except OSError:
                pass
    return changed


async def delete_project(engine: AsyncEngine, project_id: str) -> bool:
    """刪 project 本身,session 上的 project_id ref 變孤(自動視為無 project)。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "DELETE FROM cowork_projects WHERE id = ?", (project_id,),
        )
        # 同時清這個 project 在 sessions 上的 ref
        await conn.exec_driver_sql(
            "UPDATE cowork_session_ext SET project_id = NULL WHERE project_id = ?",
            (project_id,),
        )
        await conn.commit()
    return (result.rowcount or 0) > 0


async def list_sessions_in_project(
    engine: AsyncEngine, project_id: str
) -> list[str]:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT session_id FROM cowork_session_ext WHERE project_id = ?",
            (project_id,),
        )
        return [r[0] for r in result.all()]


@dataclass
class SearchHit:
    session_id: str
    title: str | None
    provider: str
    model: str
    created_at: float
    match_count: int
    snippet: str  # 第一個 match 周邊 ~100 字


def _extract_text_from_content(content_json: Any) -> str:
    """從 raw content_json 抽出可搜尋文字(text + tool_result content)。

    跳過 image / tool_use input(那是結構化資料)。Return lower-cased,給
    case-insensitive substring match 用。
    """
    if isinstance(content_json, str):
        return content_json.lower()
    if not isinstance(content_json, list):
        return ""
    parts: list[str] = []
    for b in content_json:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "text":
            parts.append(str(b.get("text", "")))
        elif btype == "tool_result":
            c = b.get("content")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                # tool_result content 可能是 list of {type:text, text:...}
                for inner in c:
                    if isinstance(inner, dict) and inner.get("type") == "text":
                        parts.append(str(inner.get("text", "")))
        elif btype == "thinking":
            parts.append(str(b.get("thinking", "")))
    return "\n".join(parts).lower()


async def search_messages(
    engine: AsyncEngine,
    query: str,
    *,
    limit: int = 50,
) -> list[SearchHit]:
    """In-memory 全文搜尋(對單機桌機 app data scale 夠用)。

    Match title + message text + tool result。skip image / blob_id / tool input。
    回 sessions 排序:match_count desc,created_at desc。
    """
    q = query.strip().lower()
    if not q:
        return []
    sessions = await list_sessions(engine)
    hits: list[SearchHit] = []
    for sess in sessions:
        # Title match 計入,但不 generate snippet(title 本身就顯在 row 上)
        title_lower = (sess.title or "").lower()
        match_count = title_lower.count(q) if title_lower else 0
        snippet = ""
        rows = await load_raw_messages(engine, sess.session_id)
        for _role, content_json in rows:
            text = _extract_text_from_content(content_json)
            if not text:
                continue
            idx = text.find(q)
            if idx < 0:
                continue
            match_count += text.count(q)
            if not snippet:
                start = max(0, idx - 30)
                end = min(len(text), idx + len(q) + 70)
                prefix = "…" if start > 0 else ""
                suffix = "…" if end < len(text) else ""
                snippet = f"{prefix}{text[start:end]}{suffix}"
        if match_count > 0:
            hits.append(SearchHit(
                session_id=sess.session_id,
                title=sess.title,
                provider=sess.provider,
                model=sess.model,
                created_at=sess.created_at,
                match_count=match_count,
                snippet=snippet,
            ))
    hits.sort(key=lambda h: (-h.match_count, -h.created_at))
    return hits[:limit]


async def migrate_inline_attachments_to_blobs(engine: AsyncEngine) -> dict[str, int]:
    """掃所有 messages row,把 inline base64 ImageBlock 抽進 blob store,
    改寫 row 為 blob ref。

    Idempotent:已是 blob ref 的 row 略過。回統計 dict {"scanned", "migrated", "blobs_written"}。
    """
    blob = get_blob_store()
    scanned = 0
    migrated_rows = 0
    blobs_written = 0
    async with db_session(engine) as s:
        stmt = select(MessageRow)
        result = await s.execute(stmt)
        for row in result.scalars():
            scanned += 1
            cj = row.content_json
            if not isinstance(cj, list):
                continue
            changed = False
            new_list = []
            for b in cj:
                if (
                    isinstance(b, dict)
                    and b.get("type") == "image"
                    and isinstance(b.get("data"), str)
                    and b["data"]
                    and "blob_id" not in b
                ):
                    try:
                        raw = base64.b64decode(b["data"])
                        blob_id = blob.put(raw)
                        new_list.append({
                            "type": "image",
                            "media_type": b.get("media_type") or "image/png",
                            "blob_id": blob_id,
                        })
                        changed = True
                        blobs_written += 1
                        continue
                    except Exception:  # noqa: BLE001
                        # 壞 base64,保留原樣
                        pass
                new_list.append(b)
            if changed:
                row.content_json = new_list
                migrated_rows += 1
        if migrated_rows:
            await s.commit()
    # SQLite TEXT row 縮小,但檔案 page 不會自動釋放。下面 VACUUM 收回磁碟。
    if migrated_rows:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("VACUUM")
    return {
        "scanned": scanned,
        "migrated_rows": migrated_rows,
        "blobs_written": blobs_written,
    }
