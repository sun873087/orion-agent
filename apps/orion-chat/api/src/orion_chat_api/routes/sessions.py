"""/sessions — REST CRUD + /models — 可選 model 清單。

- POST /sessions → 建新 conversation,可選帶 provider/model;回 session_id + provider/model
- GET /sessions → 列出 user 所有 session 摘要(含 provider/model)
- GET /sessions/{sid} → 單 session 摘要
- DELETE /sessions/{sid} → 刪 session
- GET /models → catalog + 各 provider 的 API key 是否設好(client 用來灰掉沒 key 的選項)
"""

from __future__ import annotations

import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.requests import Request

from orion_chat_api.conversation_meta import (
    fetch_budget,
    fetch_meta_map,
    fetch_permission_mode,
    session_belongs_to,
    upsert_meta,
)
from orion_chat_api.deps import (
    current_user,
    get_llm_provider,
    get_session_manager,
)
from orion_chat_api.session_manager import SessionManager
from orion_sdk.core.conversation import Conversation, pick_max_tokens_per_turn
from orion_model.catalog import list_catalog, validate
from orion_model.provider import LLMProvider, get_provider
from orion_sdk.storage.paths import session_paths
from orion_sdk.telemetry.cost_tracker import get_session_summary
from orion_sdk.tools.builtin_set import build_default_tool_set

router = APIRouter()


_PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    # Ollama 走本機 daemon 沒 API key 概念 — 空字串 → os.environ.get(...) 永遠
    # 回 falsy → "available": false。將來 ollama_provider 加 OLLAMA_HOST ping
    # 可以再升級 — 目前 ollama 在 chat-api 沒整合,留 unavailable 防 catalog
    # 撈到 ollama 時 KeyError 炸。
    "ollama": "",
}


def _provider_available(provider_id: str) -> bool:
    """Provider 是否能用 — proxy mode 統一看 proxy key,direct mode 看自家 key。

    走 proxy 時 individual provider key 由 proxy server-side 保管,client 端
    不需要也不該有 — 只要 ORION_MODEL_PROXY_URL + ORION_MODEL_PROXY_KEY 都設了,
    UI 就應該全 provider available(實際請求 fail 時 proxy 才會回 503)。
    """
    if os.environ.get("ORION_MODEL_PROXY_URL") and os.environ.get("ORION_MODEL_PROXY_KEY"):
        return True
    env_key = _PROVIDER_KEY_ENV.get(provider_id, "")
    return bool(env_key) and bool(os.environ.get(env_key))


class CreateSessionRequest(BaseModel):
    """建 session 可選指定 (provider, model)。一者帶就兩者都得帶。"""

    provider: Literal["anthropic", "openai", "google", "openrouter", "ollama"] | None = None
    model: str | None = None


class SessionSummary(BaseModel):
    session_id: UUID
    user_id: str
    n_messages: int
    n_turns: int
    provider: str
    model: str
    title: str | None = None
    starred: bool = False


class PatchSessionBody(BaseModel):
    """部分更新 — 只動有傳的欄位(用 model_fields_set 區分未傳 vs 傳 null)。"""

    title: str | None = None
    starred: bool | None = None


@router.post("/sessions", response_model=SessionSummary, status_code=status.HTTP_201_CREATED)
async def create_session(
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    default_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    body: CreateSessionRequest | None = None,
) -> SessionSummary:
    provider_for_session: LLMProvider
    if body is None or (body.provider is None and body.model is None):
        provider_for_session = default_provider
    elif body.provider is None or body.model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "must specify both 'provider' and 'model' (or neither for server default)",
        )
    else:
        if not validate(body.provider, body.model):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"invalid (provider, model): ({body.provider!r}, {body.model!r})",
            )
        if not _provider_available(body.provider):
            env_key = _PROVIDER_KEY_ENV.get(body.provider, "")
            hint = (
                f"set ORION_MODEL_PROXY_URL + ORION_MODEL_PROXY_KEY,or {env_key}"
                if env_key
                else "走 proxy 需設 ORION_MODEL_PROXY_URL + ORION_MODEL_PROXY_KEY"
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"{body.provider} not configured ({hint})",
            )
        provider_for_session = get_provider(body.provider, body.model)

    conv = Conversation(
        provider=provider_for_session,
        user_id=user_id,
        tools=build_default_tool_set(),
        max_tokens_per_turn=pick_max_tokens_per_turn(
            provider_for_session.name, provider_for_session.model,
        ),
        # Chat-api server,無 user-side cwd
        include_workspace_context=False,
    )
    sid = await sm.create(
        user_id=user_id, session_id=conv.session_id, conversation=conv,
    )
    return SessionSummary(
        session_id=sid,
        user_id=user_id,
        n_messages=0,
        n_turns=0,
        provider=provider_for_session.name,
        model=provider_for_session.model,
    )


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> list[SessionSummary]:
    items = await sm.list_for_user(user_id)
    return [
        SessionSummary(
            session_id=i.session_id,
            user_id=i.user_id,
            n_messages=i.n_messages,
            n_turns=i.n_turns,
            provider=i.provider,
            model=i.model,
            title=i.title,
            starred=i.starred,
        )
        for i in items
    ]


@router.get("/sessions/{session_id}", response_model=SessionSummary)
async def get_session(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> SessionSummary:
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    title, starred = None, False
    engine = getattr(sm, "engine", None)
    if engine is not None:
        meta = await fetch_meta_map(engine, [str(session_id)])
        title, starred = meta.get(str(session_id), (None, False))
    return SessionSummary(
        session_id=session_id,
        user_id=user_id,
        n_messages=len(conv.state_messages),
        n_turns=conv.stats.turns,
        provider=conv.provider.name,
        model=conv.provider.model,
        title=title,
        starred=starred,
    )


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
async def patch_session(
    session_id: UUID,
    body: PatchSessionBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> SessionSummary:
    """rename(title)/ 加星(starred)。需 ORION_DB_URL;只能改自己的 session。"""
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Session metadata (title/starred) requires ORION_DB_URL.",
        )
    if not await session_belongs_to(engine, str(session_id), user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    fields = body.model_fields_set
    kwargs: dict[str, object] = {}
    if "title" in fields:
        kwargs["title"] = body.title
    if "starred" in fields and body.starred is not None:
        kwargs["starred"] = body.starred
    title, starred = await upsert_meta(engine, str(session_id), **kwargs)  # type: ignore[arg-type]

    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return SessionSummary(
        session_id=session_id,
        user_id=user_id,
        n_messages=len(conv.state_messages),
        n_turns=conv.stats.turns,
        provider=conv.provider.name,
        model=conv.provider.model,
        title=title,
        starred=starred,
    )


def _message_text(message: object) -> str:
    """取 message 純文字(content 為 str 或 block list)。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts)


class ForkBody(BaseModel):
    up_to_message_index: int | None = None  # None = 整段分支
    title: str | None = None


class TruncateBody(BaseModel):
    up_to_message_index: int


class RegenerateResponse(BaseModel):
    removed_user_text: str | None = None


@router.post(
    "/sessions/{session_id}/fork",
    response_model=SessionSummary,
    status_code=status.HTTP_201_CREATED,
)
async def fork_session_route(
    session_id: UUID,
    body: ForkBody,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> SessionSummary:
    if not hasattr(sm, "fork_session"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "fork requires ORION_DB_URL",
        )
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    up_to = (
        body.up_to_message_index
        if body.up_to_message_index is not None
        else len(conv.state_messages)
    )
    new_sid = await sm.fork_session(user_id, session_id, up_to, body.title)  # type: ignore[attr-defined]
    if new_sid is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    new_conv = await sm.get(user_id, new_sid)
    assert new_conv is not None
    return SessionSummary(
        session_id=new_sid,
        user_id=user_id,
        n_messages=len(new_conv.state_messages),
        n_turns=new_conv.stats.turns,
        provider=new_conv.provider.name,
        model=new_conv.provider.model,
        title=body.title,
        starred=False,
    )


@router.post("/sessions/{session_id}/truncate")
async def truncate_session_route(
    session_id: UUID,
    body: TruncateBody,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> dict[str, int]:
    if not hasattr(sm, "truncate_session"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "truncate requires ORION_DB_URL",
        )
    n = await sm.truncate_session(user_id, session_id, body.up_to_message_index)  # type: ignore[attr-defined]
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return {"n_messages": n}


@router.post("/sessions/{session_id}/regenerate", response_model=RegenerateResponse)
async def regenerate_session_route(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> RegenerateResponse:
    """截到最後一個 user message 之前,回該則文字 — 前端重送以重生回應。"""
    if not hasattr(sm, "truncate_session"):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "regenerate requires ORION_DB_URL",
        )
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    msgs = conv.state_messages
    last_user_idx = next(
        (i for i in range(len(msgs) - 1, -1, -1) if getattr(msgs[i], "role", None) == "user"),
        None,
    )
    if last_user_idx is None:
        return RegenerateResponse(removed_user_text=None)
    text = _message_text(msgs[last_user_idx])
    await sm.truncate_session(user_id, session_id, last_user_idx)  # type: ignore[attr-defined]
    return RegenerateResponse(removed_user_text=text)


@router.post("/sessions/{session_id}/compact")
async def compact_session_route(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
    force: bool = False,
) -> dict[str, object]:
    """壓縮歷史(SDK compact)。force=False 時低於門檻直接回 was_compacted=False(不打 LLM)。"""
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    result = await conv.compact(force=force)
    if result.was_compacted and hasattr(sm, "_rewrite_db_messages"):
        await sm._rewrite_db_messages(session_id, conv.state_messages)  # type: ignore[attr-defined]
        await sm.sync_stats(user_id, session_id)
    return {
        "was_compacted": result.was_compacted,
        "summary": result.summary,
        "n_messages": len(conv.state_messages),
    }


@router.get("/sessions/{session_id}/cost")
async def session_cost(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> dict[str, object]:
    """回該 session 的 token / cost 摘要。"""
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    summary = get_session_summary(str(session_id))
    if summary is None:
        return {
            "session_id": str(session_id),
            "user_id": user_id,
            "total_cost_usd": 0.0,
            "cache_hit_ratio": 0.0,
            "total_api_duration_ms": 0.0,
            "by_model": {},
        }
    return summary


class PermissionModeBody(BaseModel):
    mode: Literal["ask", "act"]


class PermissionModeResponse(BaseModel):
    mode: str


@router.get(
    "/sessions/{session_id}/permission-mode", response_model=PermissionModeResponse,
)
async def get_permission_mode(
    session_id: UUID,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> PermissionModeResponse:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        return PermissionModeResponse(mode="ask")
    if not await session_belongs_to(engine, str(session_id), user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return PermissionModeResponse(
        mode=await fetch_permission_mode(engine, str(session_id)),
    )


@router.put(
    "/sessions/{session_id}/permission-mode", response_model=PermissionModeResponse,
)
async def put_permission_mode(
    session_id: UUID,
    body: PermissionModeBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> PermissionModeResponse:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "permission mode requires ORION_DB_URL",
        )
    if not await session_belongs_to(engine, str(session_id), user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    await upsert_meta(engine, str(session_id), permission_mode=body.mode)
    return PermissionModeResponse(mode=body.mode)


class BudgetBody(BaseModel):
    budget_usd_cap: float | None = None


class BudgetResponse(BaseModel):
    budget_usd_cap: float | None = None
    budget_exceeded: bool = False


@router.get("/sessions/{session_id}/budget", response_model=BudgetResponse)
async def get_budget(
    session_id: UUID,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> BudgetResponse:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "budget requires ORION_DB_URL",
        )
    if not await session_belongs_to(engine, str(session_id), user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    cap, exceeded = await fetch_budget(engine, str(session_id))
    return BudgetResponse(budget_usd_cap=cap, budget_exceeded=exceeded)


@router.put("/sessions/{session_id}/budget", response_model=BudgetResponse)
async def put_budget(
    session_id: UUID,
    body: BudgetBody,
    request: Request,
    user_id: Annotated[str, Depends(current_user)],
) -> BudgetResponse:
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "budget requires ORION_DB_URL",
        )
    if not await session_belongs_to(engine, str(session_id), user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    # 改 cap 時順手清掉 exceeded 旗標(讓使用者調高上限後能繼續)
    await upsert_meta(
        engine,
        str(session_id),
        budget_usd_cap=body.budget_usd_cap,
        budget_exceeded=False,
    )
    cap, exceeded = await fetch_budget(engine, str(session_id))
    return BudgetResponse(budget_usd_cap=cap, budget_exceeded=exceeded)


@router.get("/sessions/{session_id}/context-breakdown")
async def context_breakdown(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> dict[str, object]:
    """目前 context 的概略組成 — 各 role 字元數 + system 字元數 + 概估 token(chars/4)。

    讓 UI 顯示「context 被誰占用」。token 用 chars/4 概估(免額外 tokenizer 依賴)。
    """
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    by_role: dict[str, int] = {}
    for m in conv.state_messages:
        text = _message_text(m)
        role = getattr(m, "role", "unknown")
        by_role[role] = by_role.get(role, 0) + len(text)
    system_chars = len(conv.system_prompt or "")
    total_chars = system_chars + sum(by_role.values())
    return {
        "n_messages": len(conv.state_messages),
        "system_chars": system_chars,
        "by_role_chars": by_role,
        "approx_total_tokens": total_chars // 4,
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> None:
    deleted = await sm.delete(user_id, session_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")


class WorkspaceFile(BaseModel):
    name: str
    size: int
    mtime: float


@router.get("/sessions/{session_id}/files", response_model=list[WorkspaceFile])
async def list_session_files(
    session_id: UUID,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> list[WorkspaceFile]:
    """列出 session workspace dir 內的檔案(模型用 Bash/Write 產出的檔)。"""
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    sp = session_paths(session_id)
    ws = sp.workspace_dir
    if not ws.exists():
        return []
    out: list[WorkspaceFile] = []
    for p in sorted(ws.iterdir()):
        if not p.is_file():
            continue
        st = p.stat()
        out.append(WorkspaceFile(name=p.name, size=st.st_size, mtime=st.st_mtime))
    return out


@router.get("/sessions/{session_id}/files/{filename}")
async def download_session_file(
    session_id: UUID,
    filename: str,
    user_id: Annotated[str, Depends(current_user)],
    sm: Annotated[SessionManager, Depends(get_session_manager)],
) -> FileResponse:
    """下載 workspace 內單一檔案。"""
    conv = await sm.get(user_id, session_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    sp = session_paths(session_id)
    ws = sp.workspace_dir.resolve()
    target = (ws / filename).resolve()
    # path traversal guard:resolved 路徑必須仍在 workspace 底下
    if ws not in target.parents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid filename")
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    return FileResponse(target, filename=target.name)


@router.get("/models")
async def list_models(
    default_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    _user_id: Annotated[str, Depends(current_user)],
) -> dict[str, object]:
    """回 catalog + 哪個 provider 的 API key 設好了(UI 用來灰掉沒 key 的選項)。"""
    catalog = list_catalog()
    providers_raw = catalog["providers"]
    assert isinstance(providers_raw, list)
    providers = [
        {**p, "available": _provider_available(str(p["id"]))}
        for p in providers_raw
    ]
    return {
        "providers": providers,
        "default": {
            "provider": default_provider.name,
            "model": default_provider.model,
        },
    }
