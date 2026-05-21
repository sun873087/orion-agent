"""Pane role loader。

跟 skills 同一套 markdown + frontmatter pattern,但 schema 較窄(role 只關心
prompt addendum + 預設工具 / permission 設定)。

User 在 `~/.orion/users/<u>/roles/<name>/ROLE.md` 新增 / 覆寫;bundled 的 4 個
defaults(researcher / coder / reviewer / doc-writer)以 SDK 包進來。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from importlib.resources import as_file, files
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 200 * 1024


@dataclass
class Role:
    """Loaded role。"""

    name: str
    description: str = ""
    body: str = ""
    """Prompt addendum — append 進 system_prompt。"""
    default_disabled_tools: list[str] = field(default_factory=list)
    """逗號分隔字串解析後的工具名 list。建 pane 時拿來預設關掉這些 tools。"""
    default_permission_mode: str | None = None
    """`ask` / `act` / None(用 user 預設)。"""
    source_path: Path | None = None


def _parse_role_md(md_path: Path, default_name: str) -> Role | None:
    """Parse 一個 markdown(ROLE.md 或 flat .md)成 Role。失敗回 None。"""
    try:
        size = md_path.stat().st_size
    except OSError:
        return None
    if size > _MAX_FILE_BYTES:
        logger.warning("role %s too large (%d bytes) — skipping", md_path, size)
        return None
    try:
        post = frontmatter.load(md_path)
    except Exception as e: # noqa: BLE001
        logger.warning("failed to parse role %s: %s", md_path, e)
        return None

    meta = post.metadata or {}
    name = str(meta.get("name") or default_name)
    desc = str(meta.get("description") or "")
    body = post.content or ""

    disabled_raw = meta.get("default_disabled_tools")
    if isinstance(disabled_raw, list):
        disabled = [str(x).strip() for x in disabled_raw if str(x).strip()]
    elif isinstance(disabled_raw, str):
        disabled = [t.strip() for t in disabled_raw.split(",") if t.strip()]
    else:
        disabled = []

    perm_raw = meta.get("default_permission_mode")
    perm = str(perm_raw).strip() if perm_raw else None
    if perm not in ("ask", "act", None, ""):
        perm = None

    try:
        return Role(
            name=name,
            description=desc,
            body=body,
            default_disabled_tools=disabled,
            default_permission_mode=perm or None,
            source_path=md_path,
        )
    except Exception as e: # noqa: BLE001
        logger.warning("failed to build role from %s: %s", md_path, e)
        return None


def load_roles_dir(directory: Path) -> list[Role]:
    """掃單一目錄,parse roles。支援 `<dir>/<name>/ROLE.md`(慣例)+ flat `*.md`(舊式)。"""
    if not directory.exists() or not directory.is_dir():
        return []

    roles: list[Role] = []

    # 慣例:子資料夾 + ROLE.md
    for sub in sorted(directory.iterdir()):
        if not sub.is_dir():
            continue
        role_md = sub / "ROLE.md"
        if not role_md.is_file():
            continue
        r = _parse_role_md(role_md, default_name=sub.name)
        if r is not None:
            roles.append(r)

    # backwards-compat:flat *.md(排除 README.md)
    _SKIP_FLAT = {"ROLE.md", "README.md"}
    for md_path in sorted(directory.glob("*.md")):
        if not md_path.is_file() or md_path.name in _SKIP_FLAT:
            continue
        r = _parse_role_md(md_path, default_name=md_path.stem)
        if r is not None:
            roles.append(r)

    return roles


def _bundled_roles() -> list[Role]:
    """從 SDK package data 載入 bundled roles。"""
    try:
        bundled_root = files("orion_sdk.roles") / "bundled"
    except (ModuleNotFoundError, FileNotFoundError):
        return []
    try:
        with as_file(bundled_root) as real_path:
            return load_roles_dir(Path(real_path))
    except (FileNotFoundError, NotADirectoryError):
        return []


def _user_roles_root() -> Path:
    """per-user roles 根目錄。對齊 skills 環境變數 pattern。"""
    return Path(
        os.environ.get(
            "ORION_USER_ROLES_DIR", str(Path.home() / ".orion" / "users"),
        ),
    )


def _user_roles_dir(user_id: str) -> Path:
    safe = user_id.replace("/", "_").replace("\\", "_").lstrip(".")
    return _user_roles_root() / safe / "roles"


def load_all_roles(user_id: str | None = None) -> list[Role]:
    """合併 bundled + user roles,同 name 則 user 覆蓋 bundled(last-wins)。"""
    by_name: dict[str, Role] = {}
    for r in _bundled_roles():
        by_name[r.name] = r
    if user_id:
        for r in load_roles_dir(_user_roles_dir(user_id)):
            by_name[r.name] = r
    return list(by_name.values())


def get_user_roles_dir(user_id: str) -> Path:
    """Public — 給 RPC 寫 / 刪 role 用。"""
    return _user_roles_dir(user_id)
