"""Migration framework + 三個範例 migrations。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_sdk.migrations.framework import (
    Migration,
    MigrationRunner,
    run_pending_migrations,
)
from orion_sdk.migrations.m_01_add_default_model import (
    MIGRATION as M01,
)
from orion_sdk.migrations.m_02_normalize_mcp_servers import (
    MIGRATION as M02,
)
from orion_sdk.migrations.m_03_add_permissions_block import (
    MIGRATION as M03,
)


def test_no_pending_when_at_current() -> None:
    runner = MigrationRunner([M01, M02, M03])
    settings = {"_schema_version": "03"}
    assert runner.get_pending(settings) == []


def test_skip_already_applied() -> None:
    """已套用 v01 → v02/v03 仍 pending,v01 不重跑。"""
    runner = MigrationRunner([M01, M02, M03])
    settings = {"_schema_version": "01", "model": "claude-haiku-4-5"}
    pending = runner.get_pending(settings)
    assert [m.version for m in pending] == ["02", "03"]


def test_idempotent_double_apply() -> None:
    runner = MigrationRunner([M01])
    settings: dict[str, object] = {}
    s1, _ = runner.migrate(settings)
    s2, applied = runner.migrate(s1)
    assert applied == [] # 第二次跑空
    assert s2 == s1


def test_m01_adds_default_model() -> None:
    s, _ = MigrationRunner([M01]).migrate({})
    assert s["model"] == "claude-sonnet-4-6"
    assert s["_schema_version"] == "01"


def test_m01_does_not_overwrite() -> None:
    runner = MigrationRunner([M01])
    s, _ = runner.migrate({"model": "gpt-5"})
    assert s["model"] == "gpt-5"


def test_m02_wraps_string_mcp_command() -> None:
    runner = MigrationRunner([M01, M02])
    s, applied = runner.migrate({"mcpServers": {"github": "gh-mcp"}})
    assert "01" in applied and "02" in applied
    assert s["mcpServers"]["github"] == {"command": "gh-mcp", "type": "stdio"}


def test_m02_keeps_dict_intact() -> None:
    s, _ = MigrationRunner([M02]).migrate(
        {"mcpServers": {"slack": {"command": "slack-mcp", "type": "stdio"}}}
    )
    assert s["mcpServers"]["slack"]["command"] == "slack-mcp"


def test_m03_creates_permissions_block() -> None:
    s, _ = MigrationRunner([M03]).migrate({})
    assert s["permissions"]["rules"] == []


def test_m03_preserves_existing_rules() -> None:
    settings = {
        "permissions": {"rules": [{"tool_name": "Bash", "decision": "allow"}]}
    }
    s, _ = MigrationRunner([M03]).migrate(settings)
    assert len(s["permissions"]["rules"]) == 1


def test_failure_stops_migration() -> None:
    """中間 migration 失敗 → 之後的不跑,already-applied stamp 留。"""

    def good(s: dict) -> dict:
        s["x"] = 1
        return s

    def bad(s: dict) -> dict:
        raise RuntimeError("kaboom")

    def never(s: dict) -> dict:
        s["never"] = True
        return s

    runner = MigrationRunner([
        Migration(version="01", description="good", up=good),
        Migration(version="02", description="bad", up=bad),
        Migration(version="03", description="never", up=never),
    ])
    with pytest.raises(RuntimeError, match="kaboom"):
        runner.migrate({})


def test_run_pending_migrations_no_settings(tmp_path: Path) -> None:
    """settings.json 不存在 → no-op,不寫檔。"""
    f = tmp_path / "settings.json"
    runner = MigrationRunner([M01])
    result = run_pending_migrations(settings_file=f, runner=runner)
    assert not f.exists()
    assert result.applied == []
    assert result.skipped_reason is not None


def test_run_pending_migrations_writes_atomically(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({}), encoding="utf-8")

    runner = MigrationRunner([M01, M02, M03])
    result = run_pending_migrations(settings_file=f, runner=runner)

    assert result.applied == ["01", "02", "03"]
    assert result.to_version == "03"
    assert result.backup_path is not None
    assert result.backup_path.exists()

    # settings 已升上來
    saved = json.loads(f.read_text())
    assert saved["_schema_version"] == "03"
    assert saved["model"] == "claude-sonnet-4-6"
    assert saved["permissions"]["rules"] == []


def test_lex_sort_versions() -> None:
    """ "10" 應該排在 "02" 之後(寬度一致才 lex sort 正確)。"""
    runner = MigrationRunner(
        [
            Migration(version="10", description="ten", up=lambda s: s),
            Migration(version="02", description="two", up=lambda s: s),
        ]
    )
    versions = [m.version for m in runner.migrations]
    assert versions == ["02", "10"]


def test_run_pending_no_pending_short_circuit(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"_schema_version": "03"}), encoding="utf-8")
    runner = MigrationRunner([M01, M02, M03])
    result = run_pending_migrations(settings_file=f, runner=runner)
    assert result.applied == []
    assert result.backup_path is None
