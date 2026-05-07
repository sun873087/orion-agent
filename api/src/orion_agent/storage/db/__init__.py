"""Phase 7 — Postgres / SQLite persistence。

SQLAlchemy 2.0 async ORM。Postgres prod / SQLite test 雙模(同 models)。

Tables:
- User           bcrypt password,Phase 8+ 加 OAuth provider
- Session        conversation metadata(session_id, user_id, created_at, updated_at)
- Message        per-turn 訊息(role, content_json, ts)
"""

from orion_agent.storage.db.engine import (
    create_db_engine,
    db_session,
    get_async_session_factory,
    init_db,
)
from orion_agent.storage.db.models import (
    Base,
    Message,
    Session,
    User,
)

__all__ = [
    "Base",
    "Message",
    "Session",
    "User",
    "create_db_engine",
    "db_session",
    "get_async_session_factory",
    "init_db",
]
