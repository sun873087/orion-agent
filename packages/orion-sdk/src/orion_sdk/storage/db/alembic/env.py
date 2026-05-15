"""Alembic env — 用我們的 ORION_DB_URL + Base.metadata。"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from orion_sdk.storage.db.models import Base

config = context.config

# 從環境變數覆蓋 sqlalchemy.url
db_url = os.environ.get("ORION_DB_URL")
if db_url:
    # alembic 用 sync driver — 把 asyncpg 換 psycopg2
    sync_url = db_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    sync_url = sync_url.replace("sqlite+aiosqlite", "sqlite")
    config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
