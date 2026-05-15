"""Settings migrations。Phase 13。

對應 TS Claude Code `src/migrations/`。等冪、版本化、可回滾。

啟動時自動跑 `run_pending_migrations()` — 會把 settings 從舊版升到 CURRENT_SCHEMA_VERSION。
"""

from orion_sdk.migrations.framework import (
    CURRENT_SCHEMA_VERSION,
    Migration,
    MigrationResult,
    MigrationRunner,
    get_runner,
    run_pending_migrations,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "Migration",
    "MigrationResult",
    "MigrationRunner",
    "get_runner",
    "run_pending_migrations",
]
