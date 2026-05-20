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
    # B per-user rate limit(requests / min);NULL or 0 = unlimited。
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # D 多 org 用;NULL = orphan / 個人。
    organization_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
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


class AuditLog(Base):
    """Admin action audit — 誰 / 何時 / 對哪 entity 做了什麼。

    For compliance / 出事查 — admin 改 budget / revoke key / 刪 user 等都記。
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # e.g. "user.create", "user.delete", "key.create", "key.revoke",
    # "key.rotate", "budget.set", "webhook.set"
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "user" / "key" / "webhook" / ...
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded extra(e.g. {"new_budget": 50.0, "old_budget": 20.0})


Index("idx_audit_ts", AuditLog.ts)


class Webhook(Base):
    """webhook config — budget threshold 觸發 POST 給這 URL。

    每個 user 可有多筆 webhook(預算 80% / 100% / revoke 等不同 event)。
    """

    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    ) # NULL = 系統級(所有 user 共用,e.g. ops Slack)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    # "budget.warning_80" / "budget.exceeded" / "key.revoked" / "user.created"
    url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RoutingAlias(Base):
    """routing alias — per-user model override。
    Client 送 'auto-fast' → proxy lookup → 改成 'gpt-5-mini' forward。
    """

    __tablename__ = "routing_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    ) # NULL = global default
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    target_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    target_model: Mapped[str] = mapped_column(String(128), nullable=False)


class PromptCache(Base):
    """prompt cache layer — content hash → cached response。

    Hash 算 system prompt + messages 後存。read hit 省 upstream cost。
    """

    __tablename__ = "prompt_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    response_blob: Mapped[bytes] = mapped_column(nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)


Index("idx_prompt_cache_hash", PromptCache.content_hash)


class Organization(Base):
    """multi-org — flat users 升 multi-tenant org tree。"""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class UsageMonthlyRollup(Base):
    """歸檔表 — 90 天前的 usage_log row 壓進這 monthly granularity 表,
    然後 usage_log 砍。Admin UI 月用量 chart 走這。"""

    __tablename__ = "usage_monthly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False) # "2026-05"
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


Index("idx_usage_monthly_user_ym", UsageMonthlyRollup.user_id, UsageMonthlyRollup.year_month)


__all__ = [
    "ApiKey", "AuditLog", "Base", "Organization", "PromptCache",
    "RoutingAlias", "UsageLog", "UsageMonthlyRollup", "User", "Webhook",
]
