"""SQLAlchemy 2.0 ORM models。

Phase 7 範圍:User / Session / Message。Phase 8+ 加 PluginInstall / Hook / etc.

設計:
- UUIDs 作 primary key(string column,跨 DB 兼容)
- `content_json` 用 JSON column(PG 用 JSONB,SQLite 用 TEXT)
- timestamps 用 datetime,timezone-aware UTC
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
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
