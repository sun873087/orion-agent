"""Cowork local SQLite persistence。

跟 chat-api 的 DbSessionManager 不同:
- Single-user 模式 — 用固定 dummy user "cowork-local"
- 不依賴 fastapi / jwt(只用 orion-sdk storage primitives)
- Root 跟 CLI / chat-api 共用 `~/.orion/`,sessions 透過子目錄 + 不同檔名隔離:
    `~/.orion/sessions/cowork.db` Cowork DB(本檔案管理)
    `~/.orion/sessions/cli.db` CLI 的 DB(不在這檔案管轄)
- `$ORION_COWORK_DATA_DIR` env 可覆蓋 root(e2e test 用),DB 仍走 sessions/cowork.db

Public API:
    init_storage() -> engine # call once at startup
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

from sqlalchemy import delete, func, select
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
    """Cowork user data root — 與 CLI / chat-api 共用 `~/.orion/`。

    `ORION_COWORK_DATA_DIR` env 仍可覆蓋(e2e 測試用)。其他 host
    (CLI / chat-api)也用 `~/.orion/`,所以 skills / memory / mcp.json 自然共享;
    sessions 透過子目錄 + 不同檔名隔離(cowork.db vs cli.db),不互相干擾。
    """
    env = os.environ.get("ORION_COWORK_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".orion"


def _db_url() -> str:
    """Cowork sessions DB 落 ~/.orion/sessions/cowork.db(CLI 走 cli.db 不會撞)。"""
    sessions_dir = data_dir() / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{sessions_dir / 'cowork.db'}"


def get_blob_store() -> BlobStore:
    """Singleton blob store。跟 CLI 共用 ~/.orion/blobs/(blob_id 是 hash 不會撞)。"""
    return BlobStore(data_dir() / "blobs")


def _persist_image_blocks(content_value: Any, blob: BlobStore) -> Any:
    """寫前處理:list 內 image dict 的 inline base64 data 抽 blob,改成 ref。

    Input: list[dict],dict 可能含 {type: "image", media_type, data: base64-str}
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
            except Exception: # noqa: BLE001
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
       - cowork_schedules:排程任務(time-based 觸發 Skill / prompt)
       - cowork_collaborations:multi-pane collaboration 容器
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
        # Idempotent column additions for older DBs(SQLite 無 IF NOT EXISTS for ADD COLUMN)
        for col_def in (
            "scheduled_by_id TEXT",
            "scheduled_by_name TEXT",
            "starred INTEGER NOT NULL DEFAULT 0",
            # Plan Mode— per-session plan state 持久化:
            "plan_mode_status TEXT", # 'idle' / 'active' / 'awaiting_approval'
            "plan_id TEXT", # uuid12,跟 SDK PlanModeState.plan_id 對應
            "plan_file_path TEXT", # 絕對路徑 ~/.orion/plans/plan-{id}.md
            "plan_content TEXT", # 提交的 plan markdown(crash recovery 用)
            "plan_entered_at_message_index INTEGER",
            # Cost budget— 累積成本超 cap 自動 abort:
            "budget_usd_cap REAL", # NULL = 不限,>0 = 上限(USD);0 視同 NULL
            "budget_exceeded INTEGER NOT NULL DEFAULT 0", # 已觸發過 → 阻擋下一次 send
            # Fork lineage— 顯「分叉自 X」badge 用:
            "forked_from_session_id TEXT", # source session uuid
            "forked_from_message_index INTEGER", # 分叉點 chronological row index(inclusive)
            # Multi-pane collaboration—把 N 個 session 綁進同一 window/collaboration:
            "collaboration_id TEXT", # FK to cowork_collaborations.id, NULL = 一般獨立 session
            "pane_name TEXT", # @backend-coder / @reviewer / 同 collab 內唯一
            "pane_role TEXT", # researcher / coder / reviewer / doc-writer / custom
            "pane_position TEXT", # JSON {row, col, w, h, minimized},layout 還原用
            # 累積 token 用量持久化—SDK Session 表只有 input/output,沒 cache。
            # conv.stats 是 forward-only in-memory,sidecar restart 就歸 0;
            # 寫進這幾個 column 跨 process 才看得到累積 cost。
            "cum_input_tokens INTEGER NOT NULL DEFAULT 0",
            "cum_output_tokens INTEGER NOT NULL DEFAULT 0",
            "cum_cache_read_tokens INTEGER NOT NULL DEFAULT 0",
            "cum_cache_creation_tokens INTEGER NOT NULL DEFAULT 0",
            "cum_turns INTEGER NOT NULL DEFAULT 0",
            # Cost breakdown JSON — per-origin 累計成本,可拆細給 UI 顯示
            # {chat / subagent / compact / title / follow_ups / explain / summarize: {
            #     "input_tokens": int, "output_tokens": int,
            #     "cache_read_tokens": int, "cache_creation_tokens": int,
            #     "cost_usd": float, "count": int,
            #     "provider": str, "model": str  # 最後一次用的 provider/model(顯示用)
            # }}
            # 為什麼存 JSON 而不另開 cost_entries 表:每個 origin 只要 aggregate
            # 不需要逐筆 audit;查詢只在 turn 結束 / cost_breakdown RPC 時讀,
            # 不會被高頻 join。Schema 演進加新 origin 也不必 migration。
            "cost_breakdown_json TEXT",
        ):
            try:
                await conn.exec_driver_sql(
                    f"ALTER TABLE cowork_session_ext ADD COLUMN {col_def}"
                )
            except Exception: # noqa: BLE001
                pass # duplicate column — OK
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
        await conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS cowork_schedules (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'cowork-local',
                project_id TEXT,
                name TEXT NOT NULL,
                cron_expr TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at REAL,
                next_run_at REAL,
                last_run_session_id TEXT,
                last_run_status TEXT,
                last_error TEXT,
                model_provider TEXT,
                model TEXT,
                workspace_dir TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        # Idempotent ALTER for older DBs that pre-date target_session_id(Loop 功能加的)
        try:
            await conn.exec_driver_sql(
                "ALTER TABLE cowork_schedules ADD COLUMN target_session_id TEXT"
            )
        except Exception: # noqa: BLE001
            pass
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS cowork_schedules_enabled_idx "
            "ON cowork_schedules(enabled, next_run_at)"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS cowork_schedules_project_idx "
            "ON cowork_schedules(project_id)"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS cowork_schedules_target_session_idx "
            "ON cowork_schedules(target_session_id)"
        )
        # Multi-pane collaboration—容器表
        await conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS cowork_collaborations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                workspace_dir TEXT,
                project_id TEXT,
                budget_usd_cap REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        # 反向查詢:給 session_id 找其 collaboration / 列同 collab 所有 panes
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS cowork_session_ext_collab_idx "
            "ON cowork_session_ext(collaboration_id)"
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
    # Fork lineage— sidebar 樹狀視覺化用,None = 不是 fork 來的
    forked_from_session_id: str | None = None
    forked_from_message_index: int | None = None


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


async def update_title_if_matches(
    engine: AsyncEngine,
    session_id: str,
    expected_title: str,
    new_title: str,
) -> bool:
    # LLM 補生 title 用:只在當前 title 仍是 expected_title(規則臨時 title)時覆蓋。
    # 避免 race(user 同時手動 rename)時把使用者的名字蓋掉。
    cleaned = new_title.strip()[:60]
    if not cleaned:
        return False
    async with db_session(engine) as s:
        meta = await s.get(MetaRow, session_id)
        if meta is None or meta.title != expected_title:
            return False
        meta.title = cleaned
        await s.commit()
        return True


async def list_sessions(engine: AsyncEngine) -> list[SessionMeta]:
    """List sessions ordered by 最近活動(latest message 或 session 建立)倒序。

    空 session(沒任何 message)fallback 用 session.created_at。已有 message
    的用 MAX(message.created_at)。SQL LEFT JOIN + GROUP BY 一次撈完。
    Fork lineage(forked_from_*)同時 batch query 一次撈完,renderer 端可用
    來組樹狀 sidebar。
    """
    # Batch 一次撈 fork lineage(只挑有 fork 的;沒 fork 的 dict 內就沒 key)
    async with engine.connect() as conn:
        lineage_result = await conn.exec_driver_sql(
            "SELECT session_id, forked_from_session_id, forked_from_message_index "
            "FROM cowork_session_ext WHERE forked_from_session_id IS NOT NULL"
        )
        lineage_map: dict[str, tuple[str, int | None]] = {
            r[0]: (r[1], r[2]) for r in lineage_result.all()
        }

    async with db_session(engine) as s:
        last_msg = func.max(MessageRow.created_at)
        stmt = (
            select(SessionRow, last_msg.label("last_activity"))
            .outerjoin(MessageRow, MessageRow.session_id == SessionRow.id)
            .where(SessionRow.user_id == LOCAL_USER_ID)
            .group_by(SessionRow.id)
            .order_by(func.coalesce(last_msg, SessionRow.created_at).desc())
        )
        rows = list((await s.execute(stmt)).all())

        out: list[SessionMeta] = []
        for r, _last in rows:
            meta = await s.get(MetaRow, r.id)
            title = meta.title if meta is not None else None
            count_stmt = select(MessageRow.id).where(MessageRow.session_id == r.id)
            n = len(list((await s.execute(count_stmt)).scalars()))
            parent, msg_idx = lineage_map.get(r.id, (None, None))
            out.append(SessionMeta(
                session_id=r.id,
                provider=r.provider or "anthropic",
                model=r.model or "claude-sonnet-4-6",
                title=title,
                created_at=r.created_at.timestamp() if r.created_at else time.time(),
                n_messages=n,
                forked_from_session_id=parent,
                forked_from_message_index=msg_idx,
            ))
        return out


async def delete_many_sessions(
    engine: AsyncEngine, session_ids: list[str],
) -> dict[str, int]:
    """Bulk delete:對每個 sid 跑 cascade delete(messages / meta / ext /
    schedules / blobs / fork 子孫)。回 {requested, deleted, descendants_deleted}。

    fork 子孫去重:多個請求 session 可能互為祖孫關係,先撈所有子孫聯集,
    避免同一 session 被算進兩次刪除。
    """
    if not session_ids:
        return {"requested": 0, "deleted": 0, "descendants_deleted": 0}
    # 先找每個 sid 的所有子孫,union 起來
    all_descendants: set[str] = set()
    for sid in session_ids:
        all_descendants.update(await find_fork_descendants(engine, sid))
    # 子孫 set 扣掉本來就在 request 內的(避免重複處理)
    request_set = set(session_ids)
    extra_descendants = all_descendants - request_set
    total_targets = list(request_set | all_descendants)
    deleted = 0
    for sid in session_ids:
        # 用 delete_session 標準路徑;它內部也會找 descendants — 但因為我們
        # 已經一起列在 total_targets,實際刪重複只是 no-op(get/SessionRow
        # 已被前一輪刪掉,直接 skip 就 return False)
        ok = await delete_session(engine, sid)
        if ok:
            deleted += 1
    return {
        "requested": len(session_ids),
        "deleted": deleted,
        "descendants_deleted": len(extra_descendants),
        "total_targets": len(total_targets),
    }


async def find_fork_descendants(
    engine: AsyncEngine, session_id: str,
) -> list[str]:
    """遞迴找該 session 的所有 fork 子孫(不含 self)。BFS,SQLite 沒
    RECURSIVE CTE 支援限制,純 Python loop 比較好讀也方便除錯。 """
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT session_id, forked_from_session_id FROM cowork_session_ext "
            "WHERE forked_from_session_id IS NOT NULL"
        )
        pairs = [(r[0], r[1]) for r in result.all()]
    # parent → [child] map
    children_map: dict[str, list[str]] = {}
    for child, parent in pairs:
        children_map.setdefault(parent, []).append(child)
    out: list[str] = []
    visited: set[str] = set()
    queue: list[str] = [session_id]
    while queue:
        cur = queue.pop()
        for child in children_map.get(cur, []):
            if child in visited:
                continue
            visited.add(child)
            out.append(child)
            queue.append(child)
    return out


async def count_fork_descendants(
    engine: AsyncEngine, session_id: str,
) -> int:
    """Sidebar delete confirm 用 — 知道刪這 session 會牽動幾個 fork。 """
    return len(await find_fork_descendants(engine, session_id))


async def delete_session(engine: AsyncEngine, session_id: str) -> bool:
    """Cascade delete:DB rows + 該 session 的 blob 檔 + 綁該 session 的 Loop 排程
    + **fork 子孫**。

    Fork 子孫:用 forked_from_session_id 遞迴往下找,每個子孫都跑同樣的
    清理流程(messages / meta / ext / schedules / blob)。child fork 仍指向
    parent 的時候,parent 沒了 child 從 sidebar tree 看會變 orphan(root)
    — user 直覺是「刪母對話就把整支家族都刪掉」,所以這邊直接 cascade。

    先撈 content_json 內所有 blob_id 收集,DB rows commit 後再 unlink blob 檔
    (中途 unlink fail 不影響 DB consistency,下次 cleanup_orphan_blobs 會撿)。

    Loop 排程(`cowork_schedules.target_session_id = session_id`)同 transaction
    一起刪 — 它本來就是綁這 session 的,session 沒了排程也沒意義。純 Schedule
    (target_session_id IS NULL,fire 時開新 session)不在這範圍。
    """
    descendants = await find_fork_descendants(engine, session_id)
    targets = [session_id, *descendants]
    all_blob_ids: list[str] = []
    async with db_session(engine) as s:
        row = await s.get(SessionRow, session_id)
        if row is None:
            return False
        conn = await s.connection()
        for sid in targets:
            # blob_id ref 從各 session 的 messages 撈出來累積
            msg_rows = await s.execute(
                select(MessageRow.content_json).where(MessageRow.session_id == sid)
            )
            all_blob_ids.extend(
                _collect_blob_ids([cj for (cj,) in msg_rows])
            )
            await s.execute(delete(MessageRow).where(MessageRow.session_id == sid))
            await s.execute(delete(MetaRow).where(MetaRow.session_id == sid))
            sess_row = await s.get(SessionRow, sid)
            if sess_row is not None:
                await s.delete(sess_row)
            await conn.exec_driver_sql(
                "DELETE FROM cowork_schedules WHERE target_session_id = ?",
                (sid,),
            )
            await conn.exec_driver_sql(
                "DELETE FROM cowork_session_ext WHERE session_id = ?",
                (sid,),
            )
        await s.commit()
    # DB 已 commit;unlink blob 檔。fail 不影響 DB,下次 cleanup 會撿。
    blob = get_blob_store()
    for bid in all_blob_ids:
        try:
            blob.delete(bid)
        except Exception: # noqa: BLE001
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
    """讀 cowork_session_ext row。沒 row 回 dict with None values。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT workspace_dir, project_id, scheduled_by_id, scheduled_by_name, "
            "collaboration_id, pane_name "
            "FROM cowork_session_ext WHERE session_id = ?",
            (session_id,),
        )
        row = result.first()
    if row is None:
        return {
            "workspace_dir": None, "project_id": None,
            "scheduled_by_id": None, "scheduled_by_name": None,
            "collaboration_id": None, "pane_name": None,
        }
    return {
        "workspace_dir": row[0],
        "project_id": row[1],
        "scheduled_by_id": row[2],
        "scheduled_by_name": row[3],
        "collaboration_id": row[4],
        "pane_name": row[5],
    }


async def list_session_starred_ids(engine: AsyncEngine) -> set[str]:
    """Batch 撈所有 starred=1 的 session_id(Sidebar list 用,一次 query 解 N+1)。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT session_id FROM cowork_session_ext WHERE starred = 1"
        )
        return {row[0] for row in result.all()}


async def set_session_starred(
    engine: AsyncEngine, session_id: str, starred: bool,
) -> None:
    """Upsert starred flag。"""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (session_id, starred)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET starred = excluded.starred
            """,
            (session_id, 1 if starred else 0),
        )
        await conn.commit()


async def rename_session(
    engine: AsyncEngine, session_id: str, title: str,
) -> bool:
    """強制 update conversation_metadata.title(覆蓋既有)。"""
    async with db_session(engine) as s:
        meta = await s.get(MetaRow, session_id)
        if meta is None:
            return False
        meta.title = title[:200].strip()
        await s.commit()
    return True


async def list_session_scheduled_by_map(
    engine: AsyncEngine,
) -> dict[str, dict[str, str]]:
    """Batch 撈所有 session 的 scheduled_by 標記(Sidebar list 用,一次 query 解 N+1)。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT session_id, scheduled_by_id, scheduled_by_name "
            "FROM cowork_session_ext WHERE scheduled_by_id IS NOT NULL"
        )
        return {
            r[0]: {"id": r[1], "name": r[2] or ""}
            for r in result.all()
        }


async def set_session_scheduled_by(
    engine: AsyncEngine,
    session_id: str,
    *,
    schedule_id: str,
    schedule_name: str,
) -> None:
    """標記 session 為某 schedule 觸發產生(Sidebar 顯 badge 用)。"""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (session_id, scheduled_by_id, scheduled_by_name)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                scheduled_by_id = excluded.scheduled_by_id,
                scheduled_by_name = excluded.scheduled_by_name
            """,
            (session_id, schedule_id, schedule_name),
        )
        await conn.commit()


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


# ─── Plan Mode──────────────────────────────────────────────


async def get_plan_state(
    engine: AsyncEngine, session_id: str
) -> dict[str, Any] | None:
    """讀 session 的 plan_mode 狀態。

    回傳 dict 含 status / plan_id / plan_file_path / plan_content /
    entered_at_message_index;若 status 為 None 或 'idle' 回 None。
    """
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            """
            SELECT plan_mode_status, plan_id, plan_file_path,
                   plan_content, plan_entered_at_message_index
            FROM cowork_session_ext WHERE session_id = ?
            """,
            (session_id,),
        )
        row = result.fetchone()
    if row is None:
        return None
    status, plan_id, plan_file_path, plan_content, msg_idx = row
    if not status or status == "idle":
        return None
    return {
        "status": status,
        "plan_id": plan_id,
        "plan_file_path": plan_file_path,
        "plan_content": plan_content,
        "entered_at_message_index": msg_idx,
    }


async def save_plan_state(
    engine: AsyncEngine,
    session_id: str,
    *,
    status: str | None,
    plan_id: str | None = None,
    plan_file_path: str | None = None,
    plan_content: str | None = None,
    entered_at_message_index: int | None = None,
) -> None:
    """Upsert plan mode state。status=None 或 'idle' 等於清空整組欄位。"""
    if status is None or status == "idle":
        status = "idle"
        plan_id = None
        plan_file_path = None
        plan_content = None
        entered_at_message_index = None
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (
                session_id, plan_mode_status, plan_id, plan_file_path,
                plan_content, plan_entered_at_message_index
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                plan_mode_status = excluded.plan_mode_status,
                plan_id = excluded.plan_id,
                plan_file_path = excluded.plan_file_path,
                plan_content = excluded.plan_content,
                plan_entered_at_message_index = excluded.plan_entered_at_message_index
            """,
            (session_id, status, plan_id, plan_file_path,
             plan_content, entered_at_message_index),
        )
        await conn.commit()


async def list_awaiting_approval_sessions(
    engine: AsyncEngine,
) -> list[dict[str, Any]]:
    """掃所有 AWAITING_APPROVAL 的 session(crash recovery 用)。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            """
            SELECT session_id, plan_id, plan_file_path, plan_content
            FROM cowork_session_ext
            WHERE plan_mode_status = 'awaiting_approval'
            """,
        )
        rows = result.fetchall()
    return [
        {
            "session_id": r[0],
            "plan_id": r[1],
            "plan_file_path": r[2],
            "plan_content": r[3],
        }
        for r in rows
    ]


# ─── Cost budget──────────────────────────────────────────────


async def get_session_budget(
    engine: AsyncEngine, session_id: str
) -> dict[str, Any]:
    """讀 budget cap + exceeded flag。沒設 row 或 budget=NULL → cap=None。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT budget_usd_cap, budget_exceeded FROM cowork_session_ext "
            "WHERE session_id = ?",
            (session_id,),
        )
        row = result.first()
    if row is None:
        return {"budget_usd_cap": None, "exceeded": False}
    cap = row[0]
    # 0 視同未設(避免使用者設 0 反而立刻 block)
    if cap is not None and cap <= 0:
        cap = None
    return {"budget_usd_cap": cap, "exceeded": bool(row[1])}


async def set_session_budget(
    engine: AsyncEngine, session_id: str, budget_usd_cap: float | None
) -> None:
    """Upsert budget cap。None 或 <=0 清空。設新 cap 順便清 exceeded flag。"""
    cap_value = budget_usd_cap if (budget_usd_cap and budget_usd_cap > 0) else None
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (
                session_id, budget_usd_cap, budget_exceeded
            )
            VALUES (?, ?, 0)
            ON CONFLICT(session_id) DO UPDATE SET
                budget_usd_cap = excluded.budget_usd_cap,
                budget_exceeded = 0
            """,
            (session_id, cap_value),
        )
        await conn.commit()


async def mark_budget_exceeded(
    engine: AsyncEngine, session_id: str, exceeded: bool
) -> None:
    """Toggle exceeded flag(超過 cap → 1;raise cap 後 reset → 0)。"""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (session_id, budget_exceeded)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                budget_exceeded = excluded.budget_exceeded
            """,
            (session_id, 1 if exceeded else 0),
        )
        await conn.commit()


async def list_referenced_plan_files(engine: AsyncEngine) -> set[str]:
    """所有 session 引用的 plan_file_path(GC 用 — 不在這 set 內的就是孤兒)。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            """
            SELECT plan_file_path FROM cowork_session_ext
            WHERE plan_file_path IS NOT NULL
            """,
        )
        rows = result.fetchall()
    return {r[0] for r in rows if r[0]}


# ─── Fork──────────────────────────────────────────────


async def fork_session(
    engine: AsyncEngine,
    *,
    source_session_id: str,
    up_to_message_index: int,
    title: str | None = None,
) -> str:
    """從 source session 第 N 筆訊息(inclusive)複製到新 session。

    - 新 session 拿新 UUID,provider/model 從 source 抄
    - Message rows 完整 copy(role + content_json + metadata_json + raw_text + created_at)
      — blob_id ref 共用,blob store 是 content-hash 不會撞,delete 也用 ref counting GC
    - cowork_session_ext:workspace_dir / project_id 一起繼承;budget / plan 等 per-session
      state **不繼承**(fork 是新對話,自己跑自己的)
    - 標 forked_from_* 記分叉系譜,UI 可顯 badge

    Returns 新 session_id(uuid str)。Source session 完全不動。
    """
    from uuid import uuid4

    blob = get_blob_store()
    new_sid = str(uuid4())

    async with db_session(engine) as s:
        source = await s.get(SessionRow, source_session_id)
        if source is None:
            raise ValueError(f"source session {source_session_id!r} not found")

        # 撈 source messages 排序(同 load_messages 順序)
        stmt = (
            select(
                MessageRow.role,
                MessageRow.content_json,
                MessageRow.metadata_json,
                MessageRow.raw_text,
                MessageRow.created_at,
            )
            .where(MessageRow.session_id == source_session_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        rows = list(await s.execute(stmt))
        if up_to_message_index < 0 or up_to_message_index >= len(rows):
            raise ValueError(
                f"up_to_message_index {up_to_message_index} out of range "
                f"(source has {len(rows)} messages)"
            )

        # 建新 session,provider/model 從 source 抄
        s.add(SessionRow(
            id=new_sid,
            user_id=LOCAL_USER_ID,
            provider=source.provider,
            model=source.model,
        ))
        # Title:user 給 > source title + "(fork)" > 留空讓 LLM 自動取
        source_meta = await s.get(MetaRow, source_session_id)
        if title and title.strip():
            new_title = title.strip()[:200]
        elif source_meta is not None and source_meta.title:
            new_title = f"{source_meta.title} (fork)"[:200]
        else:
            new_title = None
        s.add(MetaRow(session_id=new_sid, title=new_title))

        # Copy messages [0..up_to_message_index] inclusive
        for role, content_json, meta, raw_text, created_at in rows[: up_to_message_index + 1]:
            s.add(MessageRow(
                session_id=new_sid,
                role=role,
                content_json=content_json,
                metadata_json=meta,
                raw_text=raw_text,
                created_at=created_at,
            ))

        await s.commit()

    # 繼承 workspace / project,標 lineage(同一個 transaction 順手解掉)
    src_ext = await get_session_ext(engine, source_session_id)
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (
                session_id, workspace_dir, project_id,
                forked_from_session_id, forked_from_message_index
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                new_sid,
                src_ext.get("workspace_dir"),
                src_ext.get("project_id"),
                source_session_id,
                up_to_message_index,
            ),
        )
        await conn.commit()

    # blob ref 繼承自然有效 — content-hash 不會 collision,delete_session 走
    # cleanup_orphan_blobs 後備掃描,不會在 source / fork 仍 ref 的時候誤刪
    _ = blob # 顯式留 ref 提醒讀者
    return new_sid


async def get_session_fork_lineage(
    engine: AsyncEngine, session_id: str
) -> dict[str, Any] | None:
    """讀 session 的 fork 系譜(沒有則 None)。Sidebar 顯 badge 用。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT forked_from_session_id, forked_from_message_index "
            "FROM cowork_session_ext WHERE session_id = ?",
            (session_id,),
        )
        row = result.first()
    if row is None or row[0] is None:
        return None
    return {
        "forked_from_session_id": row[0],
        "forked_from_message_index": row[1],
    }


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


async def record_compaction(
    engine: AsyncEngine,
    session_id: str,
    *,
    compacted_count: int,
    tombstone_msg: NormalizedMessage,
) -> None:
    """記錄一次壓縮 — soft delete(舊訊息留在 DB 給 UI history 看)+ append tombstone。

    `compacted_count`:從本 session 訊息頭算起,前 N 筆要被標記成 `compacted_out`
    (給 LLM 看的版本會 filter 掉)。`tombstone_msg`:role=user 含單一 TombstoneBlock
    的訊息,append 在最後當分隔線。

    Tombstone 的 created_at 會被刻意設成「最後一筆 compacted row」和「第一筆 kept
    row」之間,讓 chronological 排序剛好夾在中間 — UI / LLM resume 都依
    created_at 排,這樣 summary card 才會出現在壓縮點上,不會跑到最後。

    image blob 故意不 GC — 舊訊息 row 仍存在,UI scroll 回去要能看到原圖。
    """
    from datetime import timedelta

    from sqlalchemy import update

    blob = get_blob_store()
    async with db_session(engine) as s:
        # 取前 compacted_count 筆 row id + 它們的 created_at
        stmt = (
            select(MessageRow.id, MessageRow.metadata_json, MessageRow.created_at)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at, MessageRow.id)
            .limit(compacted_count)
        )
        rows = list(await s.execute(stmt))

        last_compacted_at = None
        for row_id, meta, created_at in rows:
            last_compacted_at = created_at
            new_meta = dict(meta) if isinstance(meta, dict) else {}
            new_meta["compacted_out"] = True
            await s.execute(
                update(MessageRow)
                .where(MessageRow.id == row_id)
                .values(metadata_json=new_meta)
            )

        # 第 (compacted_count+1) 筆 row 的 created_at = 第一筆 kept(若有)
        first_kept_at = None
        if last_compacted_at is not None:
            first_kept_stmt = (
                select(MessageRow.created_at)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.created_at, MessageRow.id)
                .offset(compacted_count)
                .limit(1)
            )
            row = (await s.execute(first_kept_stmt)).first()
            first_kept_at = row[0] if row else None

        # 算 tombstone 的 created_at
        tombstone_at = None
        if last_compacted_at is not None and first_kept_at is not None:
            # 夾在中間
            tombstone_at = last_compacted_at + (first_kept_at - last_compacted_at) / 2
        elif last_compacted_at is not None:
            # 沒 kept(全壓掉,理論上 SDK 會擋,保險加)→ last_compacted 後 1µs
            tombstone_at = last_compacted_at + timedelta(microseconds=1)

        # Append tombstone row(role=user, content=[TombstoneBlock dict])
        content = tombstone_msg.content
        if isinstance(content, str):
            content_value: Any = content
        else:
            content_value = [b.model_dump(mode="json") for b in content]
            content_value = _persist_image_blocks(content_value, blob)
        row_kwargs: dict[str, Any] = dict(
            session_id=session_id,
            role=tombstone_msg.role,
            content_json=content_value,
        )
        if tombstone_at is not None:
            row_kwargs["created_at"] = tombstone_at
        s.add(MessageRow(**row_kwargs))
        await s.commit()


async def truncate_messages_from(
    engine: AsyncEngine,
    session_id: str,
    *,
    raw_index: int,
) -> int:
    """從 chronological 第 N 筆 row 開始,把那筆與之後的全部 delete。

    `raw_index` 對齊 `load_raw_messages` 回傳順序(create_at + id),也就是
    `_to_ui_messages_from_raw` 給每筆 UI 訊息標的 message_index。

    Compacted_out=true 的 row 永遠在前面(壓縮點之前),所以從合理的 raw_index
    truncate 不會誤刪它們。Caller 端 UI 也應禁止對 compacted 訊息按刪除。

    回傳被刪 row 數;順便 unlink 被刪 row 引用的 image blob。
    """
    async with db_session(engine) as s:
        stmt = (
            select(MessageRow.id)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        all_ids: list[str] = [row_id for (row_id,) in await s.execute(stmt)]
        if raw_index < 0 or raw_index >= len(all_ids):
            return 0
        to_delete = all_ids[raw_index:]
        # 撈 blob_ids 再 unlink
        old_rows = await s.execute(
            select(MessageRow.content_json).where(MessageRow.id.in_(to_delete))
        )
        blob_ids = _collect_blob_ids([cj for (cj,) in old_rows])
        for row_id in to_delete:
            await s.execute(delete(MessageRow).where(MessageRow.id == row_id))
        await s.commit()
    blob = get_blob_store()
    for bid in blob_ids:
        try:
            blob.delete(bid)
        except Exception: # noqa: BLE001
            pass
    return len(to_delete)


async def load_active_messages_for_llm(
    engine: AsyncEngine,
    session_id: str,
) -> list[NormalizedMessage]:
    """LLM-facing 載入:跳過 metadata.compacted_out=True 的舊訊息。

    Resume 時用這個取代 `load_messages`,LLM context 只看 tombstone + 之後。
    UI 端走 `load_raw_messages`(回所有 rows,前端自己判斷誰是 compacted 來淡化)。
    """
    blob = get_blob_store()
    async with db_session(engine) as s:
        stmt = (
            select(MessageRow.role, MessageRow.content_json, MessageRow.metadata_json)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        rows = list(await s.execute(stmt))
    out: list[NormalizedMessage] = []
    for role, content_json, meta in rows:
        if isinstance(meta, dict) and meta.get("compacted_out"):
            continue
        hydrated = _hydrate_image_blocks(content_json, blob)
        msg = _msg_from_dict({"role": role, "content": hydrated})
        if msg is not None:
            out.append(msg)
    return out


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
) -> list[tuple[str, Any, Any]]:
    """UI lightweight 載入:不 hydrate blob,只回 (role, content_json, metadata_json) 原樣。

    切歷史時不會把 N × MB 的圖讀進記憶體,UI 拿到 ref dict 再 lazy 撈單張。
    metadata_json 帶回給 caller 判斷 compacted_out / 其他標記。
    """
    async with db_session(engine) as s:
        stmt = (
            select(MessageRow.role, MessageRow.content_json, MessageRow.metadata_json)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        rows = list(await s.execute(stmt))
    return [(role, content_json, meta) for role, content_json, meta in rows]


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
    _, content_json, _ = rows[message_index]
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
    """Workspace 為必填(B0)。建立後在 <workspace>/.orion/ 建子目錄,
    custom_instructions 同時寫到 <workspace>/.orion/instructions.md。
    """
    from uuid import uuid4
    pid = str(uuid4())
    now = time.time()
    # 建 co-located 結構
    ws_path = Path(workspace_dir).expanduser()
    cowork_dir = ws_path / ".orion"
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

    custom_instructions 變更時同步寫到 `<workspace>/.orion/instructions.md`(B4)。
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
                cowork_dir = Path(proj.workspace_dir) / ".orion"
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


async def persist_session_stats(
    engine: AsyncEngine,
    session_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    turns: int,
) -> None:
    """寫累積 token 用量進 cowork_session_ext。每 send 完呼一次。

    UPSERT — 既有 row 直接覆蓋(不 +=,因為 caller 已經傳 cumulative 值)。
    """
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext
                (session_id, cum_input_tokens, cum_output_tokens,
                 cum_cache_read_tokens, cum_cache_creation_tokens, cum_turns)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                cum_input_tokens = excluded.cum_input_tokens,
                cum_output_tokens = excluded.cum_output_tokens,
                cum_cache_read_tokens = excluded.cum_cache_read_tokens,
                cum_cache_creation_tokens = excluded.cum_cache_creation_tokens,
                cum_turns = excluded.cum_turns
            """,
            (
                session_id, input_tokens, output_tokens,
                cache_read_tokens, cache_creation_tokens, turns,
            ),
        )
        await conn.commit()


async def persist_cost_breakdown(
    engine: AsyncEngine,
    session_id: str,
    breakdown_json: str,
) -> None:
    """寫 cost breakdown JSON 進 cowork_session_ext。UPSERT 整段覆蓋。"""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext (session_id, cost_breakdown_json)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                cost_breakdown_json = excluded.cost_breakdown_json
            """,
            (session_id, breakdown_json),
        )
        await conn.commit()


async def get_cost_breakdown_json(
    engine: AsyncEngine, session_id: str,
) -> str | None:
    """讀 cost breakdown JSON。沒 row / 沒填 → None。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT cost_breakdown_json FROM cowork_session_ext WHERE session_id = ?",
            (session_id,),
        )
        row = result.first()
    if row is None:
        return None
    return row[0]


async def get_session_stats(
    engine: AsyncEngine, session_id: str,
) -> dict[str, int]:
    """讀累積 token 用量。沒 row 全回 0。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT cum_input_tokens, cum_output_tokens, cum_cache_read_tokens, "
            "cum_cache_creation_tokens, cum_turns "
            "FROM cowork_session_ext WHERE session_id = ?",
            (session_id,),
        )
        row = result.first()
    if row is None:
        return {
            "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_creation_tokens": 0, "turns": 0,
        }
    return {
        "input_tokens": row[0] or 0,
        "output_tokens": row[1] or 0,
        "cache_read_tokens": row[2] or 0,
        "cache_creation_tokens": row[3] or 0,
        "turns": row[4] or 0,
    }


async def list_sessions_in_project(
    engine: AsyncEngine, project_id: str
) -> list[str]:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT session_id FROM cowork_session_ext WHERE project_id = ?",
            (project_id,),
        )
        return [r[0] for r in result.all()]


# ─── Multi-pane collaboration ─────────────────────────────────────────────


@dataclass
class Collaboration:
    id: str
    name: str
    workspace_dir: str | None
    project_id: str | None
    budget_usd_cap: float | None
    created_at: float
    updated_at: float


@dataclass
class CollaborationPane:
    session_id: str
    collaboration_id: str
    pane_name: str
    pane_role: str | None
    pane_position: dict[str, Any] | None # JSON-decoded


def _parse_pane_position(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    import json
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else None
    except (ValueError, TypeError):
        return None


def _serialize_pane_position(pos: dict[str, Any] | None) -> str | None:
    if pos is None:
        return None
    import json
    return json.dumps(pos, separators=(",", ":"))


async def create_collaboration(
    engine: AsyncEngine,
    *,
    name: str,
    workspace_dir: str | None = None,
    project_id: str | None = None,
    budget_usd_cap: float | None = None,
) -> Collaboration:
    from uuid import uuid4
    cid = str(uuid4())
    now = time.time()
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_collaborations
                (id, name, workspace_dir, project_id, budget_usd_cap, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cid, name, workspace_dir, project_id, budget_usd_cap, now, now),
        )
        await conn.commit()
    return Collaboration(
        id=cid, name=name, workspace_dir=workspace_dir, project_id=project_id,
        budget_usd_cap=budget_usd_cap, created_at=now, updated_at=now,
    )


async def get_collaboration(
    engine: AsyncEngine, collaboration_id: str
) -> Collaboration | None:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT id, name, workspace_dir, project_id, budget_usd_cap, created_at, updated_at "
            "FROM cowork_collaborations WHERE id = ?",
            (collaboration_id,),
        )
        r = result.first()
    if r is None:
        return None
    return Collaboration(
        id=r[0], name=r[1], workspace_dir=r[2], project_id=r[3],
        budget_usd_cap=r[4], created_at=r[5], updated_at=r[6],
    )


async def list_collaborations(engine: AsyncEngine) -> list[Collaboration]:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT id, name, workspace_dir, project_id, budget_usd_cap, created_at, updated_at "
            "FROM cowork_collaborations ORDER BY updated_at DESC"
        )
        return [
            Collaboration(
                id=r[0], name=r[1], workspace_dir=r[2], project_id=r[3],
                budget_usd_cap=r[4], created_at=r[5], updated_at=r[6],
            )
            for r in result.all()
        ]


async def update_collaboration(
    engine: AsyncEngine,
    collaboration_id: str,
    *,
    name: str | None = None,
    workspace_dir: str | None = None,
    project_id: str | None = None,
    budget_usd_cap: float | None = None,
) -> bool:
    """Partial update。傳入 None 視為不動;workspace_dir / project_id 想清空請傳空字串再 caller 端處理(這裡 None 統一視為「沒指定」)。"""
    fields: list[tuple[str, Any]] = []
    if name is not None:
        fields.append(("name", name))
    if workspace_dir is not None:
        fields.append(("workspace_dir", workspace_dir or None))
    if project_id is not None:
        fields.append(("project_id", project_id or None))
    if budget_usd_cap is not None:
        fields.append(("budget_usd_cap", budget_usd_cap))
    if not fields:
        return False
    fields.append(("updated_at", time.time()))
    set_clause = ", ".join(f"{k} = ?" for k, _ in fields)
    params = [v for _, v in fields] + [collaboration_id]
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            f"UPDATE cowork_collaborations SET {set_clause} WHERE id = ?",
            tuple(params),
        )
        await conn.commit()
        return (result.rowcount or 0) > 0


async def delete_collaboration(engine: AsyncEngine, collaboration_id: str) -> bool:
    """刪 collaboration 容器;成員 session 上的 collaboration_id 變 NULL(從容器釋放,session 本身仍存在)。"""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            "UPDATE cowork_session_ext SET collaboration_id = NULL, "
            "pane_name = NULL, pane_role = NULL, pane_position = NULL "
            "WHERE collaboration_id = ?",
            (collaboration_id,),
        )
        result = await conn.exec_driver_sql(
            "DELETE FROM cowork_collaborations WHERE id = ?", (collaboration_id,),
        )
        await conn.commit()
    return (result.rowcount or 0) > 0


async def add_pane_to_collaboration(
    engine: AsyncEngine,
    *,
    collaboration_id: str,
    session_id: str,
    pane_name: str,
    pane_role: str | None = None,
    pane_position: dict[str, Any] | None = None,
) -> None:
    """把 session 綁進 collaboration 並設 pane_name / role / position。Upsert 既有 row。

    同 collab 內 pane_name 必須唯一(caller 端負責 dedupe)。
    """
    pos_text = _serialize_pane_position(pane_position)
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            """
            INSERT INTO cowork_session_ext
                (session_id, collaboration_id, pane_name, pane_role, pane_position)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                collaboration_id = excluded.collaboration_id,
                pane_name = excluded.pane_name,
                pane_role = excluded.pane_role,
                pane_position = excluded.pane_position
            """,
            (session_id, collaboration_id, pane_name, pane_role, pos_text),
        )
        await conn.exec_driver_sql(
            "UPDATE cowork_collaborations SET updated_at = ? WHERE id = ?",
            (time.time(), collaboration_id),
        )
        await conn.commit()


async def remove_pane_from_collaboration(
    engine: AsyncEngine, session_id: str,
) -> str | None:
    """把 session 從 collab 釋放(session 本身不刪)。回原 collaboration_id 給 caller。"""
    async with engine.connect() as conn:
        existing = await conn.exec_driver_sql(
            "SELECT collaboration_id FROM cowork_session_ext WHERE session_id = ?",
            (session_id,),
        )
        row = existing.first()
        old_cid = row[0] if row else None
        await conn.exec_driver_sql(
            "UPDATE cowork_session_ext SET collaboration_id = NULL, "
            "pane_name = NULL, pane_role = NULL, pane_position = NULL "
            "WHERE session_id = ?",
            (session_id,),
        )
        if old_cid:
            await conn.exec_driver_sql(
                "UPDATE cowork_collaborations SET updated_at = ? WHERE id = ?",
                (time.time(), old_cid),
            )
        await conn.commit()
        return old_cid


async def list_collaboration_panes(
    engine: AsyncEngine, collaboration_id: str
) -> list[CollaborationPane]:
    """同 collab 的所有 pane(session_id + 名字 + 角色 + position)。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT session_id, collaboration_id, pane_name, pane_role, pane_position "
            "FROM cowork_session_ext WHERE collaboration_id = ? "
            "ORDER BY pane_name",
            (collaboration_id,),
        )
        return [
            CollaborationPane(
                session_id=r[0],
                collaboration_id=r[1],
                pane_name=r[2] or "",
                pane_role=r[3],
                pane_position=_parse_pane_position(r[4]),
            )
            for r in result.all()
        ]


async def get_collaboration_for_session(
    engine: AsyncEngine, session_id: str
) -> tuple[str | None, str | None, str | None]:
    """給 session_id → (collaboration_id, pane_name, pane_role)。沒綁回 (None, None, None)。

    AskPaneTool / 跨 pane query 用 — 從目前 session 知道自己屬於哪個 collab 才能找對方。
    """
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT collaboration_id, pane_name, pane_role "
            "FROM cowork_session_ext WHERE session_id = ?",
            (session_id,),
        )
        row = result.first()
    if row is None or row[0] is None:
        return (None, None, None)
    return (row[0], row[1], row[2])


async def find_collaboration_pane(
    engine: AsyncEngine, collaboration_id: str, pane_name: str
) -> CollaborationPane | None:
    """同 collab 內,by pane_name 找 pane。 AskPaneTool 用。"""
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT session_id, collaboration_id, pane_name, pane_role, pane_position "
            "FROM cowork_session_ext WHERE collaboration_id = ? AND pane_name = ?",
            (collaboration_id, pane_name),
        )
        r = result.first()
    if r is None:
        return None
    return CollaborationPane(
        session_id=r[0], collaboration_id=r[1], pane_name=r[2] or "",
        pane_role=r[3], pane_position=_parse_pane_position(r[4]),
    )


async def update_pane_position(
    engine: AsyncEngine,
    session_id: str,
    pane_position: dict[str, Any] | None,
) -> bool:
    """更新 pane 的 position(layout 改動時 caller 端持續存)。"""
    pos_text = _serialize_pane_position(pane_position)
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "UPDATE cowork_session_ext SET pane_position = ? "
            "WHERE session_id = ? AND collaboration_id IS NOT NULL",
            (pos_text, session_id),
        )
        await conn.commit()
        return (result.rowcount or 0) > 0


async def get_collaboration_cost_summary(
    engine: AsyncEngine, collaboration_id: str
) -> dict[str, Any]:
    """加總 collab 內所有 session 的 input/output token 與成本估算。

    成本 = sum(messages.input + cache + output tokens 對應 model 單價)。
    這裡只回 token 加總,實際 USD 由 caller 端算(對應 catalog 單價,model 各異)。
    """
    panes = await list_collaboration_panes(engine, collaboration_id)
    if not panes:
        return {"total_panes": 0, "panes": [], "input_tokens": 0, "output_tokens": 0}
    sids = [p.session_id for p in panes]
    placeholders = ",".join("?" * len(sids))
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            f"SELECT id, model, provider, input_tokens, output_tokens, n_turns, n_messages "
            f"FROM sessions WHERE id IN ({placeholders})",
            tuple(sids),
        )
        per_pane: dict[str, dict[str, Any]] = {}
        total_in = 0
        total_out = 0
        for row in result.all():
            per_pane[row[0]] = {
                "session_id": row[0],
                "model": row[1],
                "provider": row[2],
                "input_tokens": row[3] or 0,
                "output_tokens": row[4] or 0,
                "n_turns": row[5] or 0,
                "n_messages": row[6] or 0,
            }
            total_in += row[3] or 0
            total_out += row[4] or 0
    out_panes: list[dict[str, Any]] = []
    for p in panes:
        info = per_pane.get(p.session_id, {
            "session_id": p.session_id,
            "model": None, "provider": None,
            "input_tokens": 0, "output_tokens": 0,
            "n_turns": 0, "n_messages": 0,
        })
        out_panes.append({**info,
            "pane_name": p.pane_name,
            "pane_role": p.pane_role,
            "pane_position": p.pane_position,
        })
    return {
        "total_panes": len(panes),
        "panes": out_panes,
        "input_tokens": total_in,
        "output_tokens": total_out,
    }


@dataclass
class SearchHit:
    session_id: str
    title: str | None
    provider: str
    model: str
    created_at: float
    match_count: int
    snippet: str # 第一個 match 周邊 ~100 字


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
        for _role, content_json, _ in rows:
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


@dataclass
class Schedule:
    id: str
    user_id: str
    project_id: str | None
    name: str
    cron_expr: str
    trigger_type: str # 'skill' | 'prompt'
    payload: str
    enabled: bool
    last_run_at: float | None
    next_run_at: float | None
    last_run_session_id: str | None
    last_run_status: str | None
    last_error: str | None
    model_provider: str | None
    model: str | None
    workspace_dir: str | None
    created_at: float
    updated_at: float
    # Loop 用:有值表示 fire 時送回該既有 session(不開新);無值是「排程」行為
    target_session_id: str | None = None


def _schedule_from_row(r: Any) -> Schedule:
    return Schedule(
        id=r[0],
        user_id=r[1],
        project_id=r[2],
        name=r[3],
        cron_expr=r[4],
        trigger_type=r[5],
        payload=r[6],
        enabled=bool(r[7]),
        last_run_at=r[8],
        next_run_at=r[9],
        last_run_session_id=r[10],
        last_run_status=r[11],
        last_error=r[12],
        model_provider=r[13],
        model=r[14],
        workspace_dir=r[15],
        created_at=r[16],
        updated_at=r[17],
        target_session_id=r[18] if len(r) > 18 else None,
    )


_SCHEDULE_COLS = (
    "id, user_id, project_id, name, cron_expr, trigger_type, payload, enabled, "
    "last_run_at, next_run_at, last_run_session_id, last_run_status, last_error, "
    "model_provider, model, workspace_dir, created_at, updated_at, target_session_id"
)


async def list_schedules(
    engine: AsyncEngine,
    *,
    scope: str = "all", # 'user' | 'project' | 'all'
    project_id: str | None = None,
    enabled_only: bool = False,
    due_before: float | None = None,
) -> list[Schedule]:
    """Filter:
       - scope='user' → project_id IS NULL
       - scope='project' → 指定 project_id;沒給 → 全部 project-scoped
       - scope='all' → 都拿
       - enabled_only → enabled = 1
       - due_before → next_run_at <= due_before(scheduler tick 用)
    """
    where: list[str] = []
    params: list[Any] = []
    if scope == "user":
        where.append("project_id IS NULL")
    elif scope == "project":
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        else:
            where.append("project_id IS NOT NULL")
    if enabled_only:
        where.append("enabled = 1")
    if due_before is not None:
        where.append("(next_run_at IS NOT NULL AND next_run_at <= ?)")
        params.append(due_before)
    sql = f"SELECT {_SCHEDULE_COLS} FROM cowork_schedules"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC"
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(sql, tuple(params))
        return [_schedule_from_row(r) for r in result.all()]


async def get_schedule(engine: AsyncEngine, schedule_id: str) -> Schedule | None:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            f"SELECT {_SCHEDULE_COLS} FROM cowork_schedules WHERE id = ?",
            (schedule_id,),
        )
        r = result.first()
    return _schedule_from_row(r) if r else None


async def create_schedule(
    engine: AsyncEngine,
    *,
    name: str,
    cron_expr: str,
    trigger_type: str,
    payload: str,
    project_id: str | None = None,
    enabled: bool = True,
    next_run_at: float | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    workspace_dir: str | None = None,
    target_session_id: str | None = None,
) -> Schedule:
    from uuid import uuid4
    sid = str(uuid4())
    now = time.time()
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            f"INSERT INTO cowork_schedules ({_SCHEDULE_COLS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid, LOCAL_USER_ID, project_id, name, cron_expr, trigger_type,
                payload, 1 if enabled else 0,
                None, next_run_at, None, None, None,
                model_provider, model, workspace_dir,
                now, now,
                target_session_id,
            ),
        )
        await conn.commit()
    got = await get_schedule(engine, sid)
    assert got is not None
    return got


async def update_schedule(
    engine: AsyncEngine,
    schedule_id: str,
    *,
    name: str | None = None,
    cron_expr: str | None = None,
    trigger_type: str | None = None,
    payload: str | None = None,
    project_id: str | None = None,
    enabled: bool | None = None,
    next_run_at: float | None = None,
    model_provider: str | None = None,
    model: str | None = None,
    workspace_dir: str | None = None,
    _clear_project: bool = False,
) -> bool:
    """部分更新;None = 不動。`_clear_project=True` 把 project_id 設成 NULL。"""
    fields: list[tuple[str, Any]] = []
    if name is not None:
        fields.append(("name", name))
    if cron_expr is not None:
        fields.append(("cron_expr", cron_expr))
    if trigger_type is not None:
        fields.append(("trigger_type", trigger_type))
    if payload is not None:
        fields.append(("payload", payload))
    if _clear_project:
        fields.append(("project_id", None))
    elif project_id is not None:
        fields.append(("project_id", project_id))
    if enabled is not None:
        fields.append(("enabled", 1 if enabled else 0))
    if next_run_at is not None:
        fields.append(("next_run_at", next_run_at))
    if model_provider is not None:
        fields.append(("model_provider", model_provider or None))
    if model is not None:
        fields.append(("model", model or None))
    if workspace_dir is not None:
        fields.append(("workspace_dir", workspace_dir or None))
    if not fields:
        return False
    fields.append(("updated_at", time.time()))
    set_clause = ", ".join(f"{k} = ?" for k, _ in fields)
    params = [v for _, v in fields] + [schedule_id]
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            f"UPDATE cowork_schedules SET {set_clause} WHERE id = ?",
            tuple(params),
        )
        await conn.commit()
    return (result.rowcount or 0) > 0


async def delete_schedule(engine: AsyncEngine, schedule_id: str) -> bool:
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "DELETE FROM cowork_schedules WHERE id = ?", (schedule_id,),
        )
        await conn.commit()
    return (result.rowcount or 0) > 0


async def record_schedule_run(
    engine: AsyncEngine,
    schedule_id: str,
    *,
    last_run_at: float,
    next_run_at: float | None,
    last_run_session_id: str | None,
    status: str, # 'ok' | 'error' | 'skipped'
    error: str | None = None,
) -> None:
    """寫一次 fire 結果。即使 status='error' 也要更新 next_run_at 往前推,
    否則同一筆 schedule 會在每個 tick 重試到天荒地老。"""
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            "UPDATE cowork_schedules SET "
            "last_run_at = ?, next_run_at = ?, last_run_session_id = ?, "
            "last_run_status = ?, last_error = ?, updated_at = ? "
            "WHERE id = ?",
            (
                last_run_at, next_run_at, last_run_session_id,
                status, error, time.time(), schedule_id,
            ),
        )
        await conn.commit()


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
                    except Exception: # noqa: BLE001
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
