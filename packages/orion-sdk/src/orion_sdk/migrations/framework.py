"""Settings migrations 框架。Phase 13。對應 TS `src/migrations/`。

設計原則:
  - **等冪**:同 version 跑多次行為一致(已套用就跳)
  - **版本化**:settings.json 內 `_schema_version` 欄位記載當前已套到哪
  - **可回滾**:每個 migration 可選 down(MVP 沒實際用,提供介面)
  - **atomic + backup**:跑完寫回前先 backup 到 `settings.json.bak.<ts>`
  - 啟動時 `run_pending_migrations()` 自動跑

加新 migration 流程:
  1. 寫 `migrations/m_NN_<slug>.py`,exporting `up: dict -> dict`(可選 `down`)
  2. 在 `_collect_migrations()` 加進 ALL_MIGRATIONS list
  3. 升 CURRENT_SCHEMA_VERSION 到該 NN
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from orion_sdk.settings import (
    load_settings,
    save_settings,
    settings_path,
)

log = structlog.get_logger()


CURRENT_SCHEMA_VERSION = "03"
"""**升級此版號的時機**:加新 migration 後,把這裡升到該 migration 的 version。"""

_INITIAL_VERSION = "00"
"""未套用任何 migration 的初始狀態(沒 `_schema_version` 欄位等同於這個)。"""

_SETTINGS_VERSION_KEY = "_schema_version"


SettingsDict = dict[str, Any]
MigrationFn = Callable[[SettingsDict], SettingsDict]


@dataclass(frozen=True)
class Migration:
    """單一遷移描述。

    `up(settings) -> settings` 必須:
    - 拿舊 settings dict,**回新 dict**(可 mutate 同一個也可以,但要回它)
    - **不要動** `_schema_version`(framework 會自動 stamp)
    - 失敗 raise 任意 exception(framework 會 log + abort)
    """

    version: str
    """新版號,e.g. "01"。字串 lex-sort 為遷移執行順序。"""

    description: str
    """一句描述,會寫進 log。"""

    up: MigrationFn

    down: MigrationFn | None = None
    """可選 rollback。Phase 13 不提供 CLI 觸發,只是介面就位。"""


@dataclass
class MigrationResult:
    """run_pending_migrations 結果。"""

    from_version: str = _INITIAL_VERSION
    to_version: str = _INITIAL_VERSION
    applied: list[str] = field(default_factory=list)
    """套用的 migration version list(空表示沒有 pending)。"""

    backup_path: Path | None = None
    """跑前的 settings 備份位置(None 表示沒備份 — 通常是 settings 不存在 / 沒 pending)。"""

    skipped_reason: str | None = None
    """沒跑的原因(no settings file / no pending),供 caller 寫 log。"""


class MigrationRunner:
    """Migration 執行器。

    `migrate(settings_dict) -> (new_settings_dict, applied_versions)`
    純函式 — 不碰 fs。caller 自己決定何時 save。`run_pending_migrations()` 是
    高階 wrapper,連 fs read/write/backup 都包好。
    """

    def __init__(self, migrations: list[Migration]) -> None:
        # 字串 lex 排序(假設 "01" "02" ... "99" 寬度一致)
        self.migrations = sorted(migrations, key=lambda m: m.version)

    def get_current_version(self, settings: SettingsDict) -> str:
        v = settings.get(_SETTINGS_VERSION_KEY)
        return v if isinstance(v, str) else _INITIAL_VERSION

    def get_pending(self, settings: SettingsDict) -> list[Migration]:
        current = self.get_current_version(settings)
        return [m for m in self.migrations if m.version > current]

    def migrate(
        self, settings: SettingsDict,
    ) -> tuple[SettingsDict, list[str]]:
        """跑所有 pending migrations。

        Returns:
            (new_settings, applied_versions)。settings 為 deep-ish 結果(每個 up
            被允許 mutate 同 dict),applied_versions 是真正套用的 version list。
        """
        pending = self.get_pending(settings)
        if not pending:
            return settings, []

        applied: list[str] = []
        for m in pending:
            try:
                settings = m.up(settings)
                settings[_SETTINGS_VERSION_KEY] = m.version
                applied.append(m.version)
                log.info(
                    "migration_applied",
                    version=m.version,
                    description=m.description,
                )
            except Exception as e:  # noqa: BLE001
                log.error(
                    "migration_failed",
                    version=m.version,
                    description=m.description,
                    error=str(e),
                )
                # 不繼續往後跑;已套用的版本 stamp 還在
                raise
        return settings, applied


# ─── 啟動時包裝(跟 fs / settings.json 互動)──────────────────────────────


def _backup_settings(path: Path) -> Path | None:
    """跑 migration 前複製 settings 到 `.bak.<ts>`。失敗回 None(不阻擋)。"""
    if not path.exists():
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(f".json.bak.{ts}")
    try:
        shutil.copy2(path, backup)
    except OSError as e:
        log.warning("settings_backup_failed", error=str(e))
        return None
    return backup


def run_pending_migrations(
    *,
    settings_file: Path | None = None,
    runner: MigrationRunner | None = None,
) -> MigrationResult:
    """讀 settings → 跑 pending → 寫回(atomic)+ backup。

    啟動時 `lifespan` 內呼叫一次。冪等 — 沒 pending 就 no-op。

    Args:
        settings_file: 預設用 `orion_sdk.settings.settings_path()`。
        runner: 預設用 `get_runner()`(內建 ALL_MIGRATIONS)。

    Returns:
        MigrationResult — caller 可寫 log 或顯示在 UI。
    """
    sp = settings_file or settings_path()
    r = runner or get_runner()

    if not sp.exists():
        # 沒 settings = 全新 user。不寫檔(避免「啟動就生 settings」)
        return MigrationResult(
            from_version=_INITIAL_VERSION,
            to_version=_INITIAL_VERSION,
            skipped_reason="settings file does not exist",
        )

    settings = load_settings(sp)
    from_v = r.get_current_version(settings)

    pending = r.get_pending(settings)
    if not pending:
        return MigrationResult(
            from_version=from_v,
            to_version=from_v,
            skipped_reason="no pending migrations",
        )

    backup = _backup_settings(sp)
    new_settings, applied = r.migrate(settings)
    save_settings(new_settings, sp)

    return MigrationResult(
        from_version=from_v,
        to_version=new_settings.get(_SETTINGS_VERSION_KEY, from_v),
        applied=applied,
        backup_path=backup,
    )


# ─── ALL_MIGRATIONS registry ────────────────────────────────────────────────


def _collect_migrations() -> list[Migration]:
    """匯總 m_*.py 模組的 Migration 物件。

    每加新 migration 在這裡顯式 import + 加 entry。集中註冊比 auto-discover 好除錯。
    """
    from orion_sdk.migrations import (
        m_01_add_default_model,
        m_02_normalize_mcp_servers,
        m_03_add_permissions_block,
    )

    return [
        m_01_add_default_model.MIGRATION,
        m_02_normalize_mcp_servers.MIGRATION,
        m_03_add_permissions_block.MIGRATION,
    ]


_RUNNER: MigrationRunner | None = None


def get_runner() -> MigrationRunner:
    """全域 runner — 第一次呼叫時 lazy 建立。"""
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = MigrationRunner(_collect_migrations())
    return _RUNNER


def reset_runner_for_test() -> None:
    """測試用:強制重新 collect(若有 monkeypatch m_*.py 模組)。"""
    global _RUNNER
    _RUNNER = None


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "Migration",
    "MigrationResult",
    "MigrationRunner",
    "get_runner",
    "reset_runner_for_test",
    "run_pending_migrations",
]
