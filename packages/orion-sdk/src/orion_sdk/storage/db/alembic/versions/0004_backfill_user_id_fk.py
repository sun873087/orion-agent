"""backfill user_id 從 username 改成 users.id — Phase 29

Phase 6/7 把 username 字串當 user_id 寫進 sessions / user_settings / user_preferences。
schema 的 FK 卻指 users.id(UUID),SQLite FK off 才沒爆。Phase 29 起 auth 層改用
user.id,本 migration 把既存資料修齊。

策略:對每張表跑 `UPDATE ... SET user_id = (SELECT id FROM users WHERE
username = <table>.user_id)`,只在「current user_id 不是任何 users.id 但是某
users.username」時動 — 已是 UUID 的新資料(Phase 29 之後寫入)不會被改。

Revision ID: 0004_backfill_user_id_fk
Revises: 0003_user_settings
Create Date: 2026-05-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_backfill_user_id_fk"
down_revision: str | None = "0003_user_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BACKFILL_TABLES = ("sessions", "user_settings", "user_preferences")


def upgrade() -> None:
    for table in _BACKFILL_TABLES:
        # 只更新 user_id 不是現存 users.id、但能在 users.username 找到的 row。
        # 兩條 NOT IN / IN subquery 保險:已是 UUID 的 row 不動,沒對應 user 的
        # 孤兒 row 也不動(後者通常是 dev 環境殘留,清掉風險高,維持原值給人工檢)。
        op.execute(
            f"""
            UPDATE {table}
            SET user_id = (
                SELECT id FROM users WHERE users.username = {table}.user_id
            )
            WHERE user_id NOT IN (SELECT id FROM users)
              AND user_id IN (SELECT username FROM users)
            """  # noqa: S608 — table name is hard-coded in _BACKFILL_TABLES, not user input
        )


def downgrade() -> None:
    # 反向:把 user_id 改回 username。production 不應該往回走,但 dev 環境可能會。
    for table in _BACKFILL_TABLES:
        op.execute(
            f"""
            UPDATE {table}
            SET user_id = (
                SELECT username FROM users WHERE users.id = {table}.user_id
            )
            WHERE user_id IN (SELECT id FROM users)
            """  # noqa: S608 — same as upgrade
        )
