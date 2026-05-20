"""SQLAlchemy ORM — users / api_keys / usage_log。

跨 SQLite + Postgres,沒用 backend-specific feature。Timestamps 統一 epoch
seconds(整數)— 跨 DB 一致 + 排序 / 算 rollup 容易。
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_used_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="api_keys")


Index("idx_api_keys_user_id", ApiKey.user_id)


class UsageLog(Base):
    __tablename__ = "usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


Index("idx_usage_user_ts", UsageLog.user_id, UsageLog.ts)


__all__ = ["ApiKey", "Base", "UsageLog", "User"]
