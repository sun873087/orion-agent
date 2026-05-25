"""SQLAlchemy 2.0 ORM models。

範圍:User / Session / Message。+ 加 PluginInstall / Hook / etc.
加 UserPreference(custom instructions / timezone)+ ConversationMetadata
(per-session title / custom instructions)。

設計:
- UUIDs 作 primary key(string column,跨 DB 兼容)
- `content_json` 用 JSON column(PG 用 JSONB,SQLite 用 TEXT)
- timestamps 用 datetime,timezone-aware UTC
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    """bcrypt hash(60 chars 通常,留 buffer 到 128)。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now,
    )

    sessions: Mapped[list[Session]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan",
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    """conversation 的 session_id(UUID 字串形式)。caller 建立時帶。"""

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )

    provider: Mapped[str] = mapped_column(String(32), default="anthropic")
    model: Mapped[str] = mapped_column(String(64), default="")

    n_turns: Mapped[int] = mapped_column(default=0)
    n_messages: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now,
    )

    user: Mapped[User] = relationship("User", back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="session",
        cascade="all, delete-orphan", order_by="Message.created_at",
    )

    __table_args__ = (
        Index("ix_sessions_user_updated", "user_id", "updated_at"),
    )

    @staticmethod
    def session_id_to_str(sid: UUID | str) -> str:
        return str(sid) if isinstance(sid, UUID) else sid


class UserSetting(Base):
    """per-user 通用 settings(JSON 值 + 樂觀鎖 version)。

    跟 `UserPreference`分開:UserPreference 是 schema-typed 欄位
    (custom_instructions / timezone / output_style 各自欄),UserSetting 是
    自由 key/value blob,給前端任意設定值用(model 偏好 / UI 偏好 / etc.)。

    composite PK = (user_id, key)。一筆 row 一個 setting。

    spec § 5.2:web chat 模式不做 diff sync,直接 REST CRUD + 樂觀鎖防多 tab race。
    """

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    """JSON column;可存 str / int / list / dict 等任何 JSON 值。"""

    version: Mapped[int] = mapped_column(default=1)
    """樂觀鎖。每次 PUT 後 +1;client 帶舊 version → 409 conflict。"""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now,
    )

    __table_args__ = (
        Index("ix_user_settings_user_id", "user_id"),
    )


class UserPreference(Base):
    """per-user 偏好(custom instructions / timezone / 等)。

    一個 user 一筆(`user_id` 是 PK + FK)。custom_instructions 對應 ChatGPT 的
    「About me / How I want help」概念 system prompt 組裝時會加進去。
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """目前選用的 output style 名稱(對應 output_styles loader)。"""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now,
    )


class ConversationMetadata(Base):
    """per-conversation metadata(title / custom instructions)。

    對應 ChatGPT 的「Custom Instructions for this chat」。session_id 為 PK + FK。
    title 由 side_query 自動產生,也可以 user 手動改。
    """

    __tablename__ = "conversation_metadata"

    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    starred: Mapped[bool | None] = mapped_column(Boolean, default=False)
    """加星標(sidebar 置頂用)。漸進欄位 → nullable;讀取以 bool(starred) 視 NULL 為 False。"""
    parent_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    """fork 來源 session（fork 樹）。"""
    forked_from_message_index: Mapped[int | None] = mapped_column(nullable=True)
    """從來源的第幾則 message 分支。"""
    budget_usd_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    """per-session 成本上限(USD)。None = 不限。"""
    budget_exceeded: Mapped[bool | None] = mapped_column(Boolean, default=False)
    """是否已超過上限(超過後拒絕新 turn)。"""
    permission_mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    """ask(每個工具問)/ act(全放行)。None → 預設 ask。"""
    plan_mode_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    """inactive / active / awaiting_approval。None → inactive。"""
    plan_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    """submit_plan 時模型寫的 plan 內容(等待 approve)。"""
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    """所屬 project(per-project 自訂指令 / workspace)。None = 無。"""
    active_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """套用的 role / persona 名;其 ROLE.md body 注入 system prompt。None = 無。"""
    collaboration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    """所屬 collaboration(多 pane 協作);此 session 即其中一個 pane。"""
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now,
    )


class Project(Base):
    """使用者的 project — 可掛 per-project 自訂指令 / workspace,組織多個 session。"""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_dir: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now,
    )


class Collaboration(Base):
    """多 pane 協作容器(限同一 user 的多個 session 並排 / 互相派工)。"""

    __tablename__ = "collaborations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now,
    )


class Schedule(Base):
    """cron 排程 / Loop(target_session_id 非 null = Loop,反覆對既有 session 注入)。"""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    cron_expr: Mapped[str] = mapped_column(String(120))
    trigger_type: Mapped[str] = mapped_column(String(16), default="prompt")
    """prompt / skill。"""
    payload: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    target_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_run_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_run_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now,
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True,
    )

    role: Mapped[str] = mapped_column(String(16))
    """user / assistant / system。"""

    content_json: Mapped[Any] = mapped_column(JSON)
    """NormalizedMessage.content 的 JSON(str 或 list[ContentBlock dict])。"""

    metadata_json: Mapped[Any] = mapped_column(
        JSON, nullable=True, default=None,
    )
    """metadata(stop_reason / token usage / 等)。"""

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    """快速 SQL search 用(content_json 取出後落 plain text)。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True,
    )

    session: Mapped[Session] = relationship("Session", back_populates="messages")
