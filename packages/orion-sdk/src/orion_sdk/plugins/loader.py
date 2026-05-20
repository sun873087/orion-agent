"""Plugin loader。

對應 TS plugins/builtinPlugins.ts + utils/plugins/pluginLoader.ts。

流程:
1. `discover_plugins(roots)` 掃多個目錄找 `*/plugin.json`
2. `get_enabled_plugins(settings)` 從 settings.json `enabledPlugins` 讀
3. `load_all_plugins(...)` 把 enabled plugin 的 hooks 註冊、skill dirs 加入、
   MCP server config 回給 caller(實際 connect 由 caller 處理)

預設 plugin roots:
- `~/.orion/plugins/`(user 全域)
- `.orion/plugins/`(專案)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orion_sdk.hooks.frontmatter import register_frontmatter_hooks
from orion_sdk.hooks.registry import HookRegistry
from orion_sdk.plugins.builtin import builtin_plugins
from orion_sdk.plugins.types import PluginManifest

logger = logging.getLogger(__name__)


def _default_user_plugin_root() -> Path:
    return Path(os.environ.get("ORION_PLUGINS_DIR", str(Path.home() / ".orion" / "plugins")))


def _project_plugin_root() -> Path:
    return Path.cwd() / ".orion" / "plugins"


def default_plugin_roots() -> list[Path]:
    return [_default_user_plugin_root(), _project_plugin_root()]


def discover_plugins(roots: list[Path]) -> list[PluginManifest]:
    """掃多個 root 目錄找 `<plugin>/plugin.json`,parse 成 PluginManifest list。"""
    found: list[PluginManifest] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for manifest_path in sorted(root.glob("*/plugin.json")):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("failed to parse %s: %s", manifest_path, e)
                continue
            if not isinstance(data, dict) or "name" not in data:
                logger.warning("invalid plugin manifest at %s", manifest_path)
                continue
            try:
                m = PluginManifest(
                    name=str(data["name"]),
                    version=str(data.get("version", "0.0.0")),
                    description=str(data.get("description", "")),
                    skills=list(data.get("skills", [])),
                    hooks=list(data.get("hooks", [])),
                    mcp_servers=dict(data.get("mcp_servers", {})),
                    source=manifest_path.parent,
                )
            except Exception as e: # noqa: BLE001
                logger.warning("failed to build PluginManifest from %s: %s", manifest_path, e)
                continue
            found.append(m)
    return found


def get_enabled_plugins(settings: dict[str, Any]) -> set[str]:
    """從 settings.json 讀 `enabledPlugins` list(預設空 — 全 disabled)。"""
    raw = settings.get("enabledPlugins", [])
    if not isinstance(raw, list):
        return set()
    return {str(x) for x in raw}


@dataclass
class PluginLoadResult:
    """`load_all_plugins` 回傳。"""

    loaded: list[PluginManifest]
    """成功 enable 的 plugin。"""

    skill_dirs: list[Path]
    """plugin 提供的 skill 目錄(skills/ 子目錄,或 manifest 指定的個別檔資料夾)。"""

    mcp_servers: dict[str, dict[str, Any]]
    """合併後的 MCP server config(plugin_name__server_name → config)。"""

    hooks_registered: int
    """總計註冊的 hook 數。"""


def load_all_plugins(
    settings: dict[str, Any],
    *,
    hook_registry: HookRegistry,
    web_only: bool = False,
    extra_roots: list[Path] | None = None,
) -> PluginLoadResult:
    """掃 + filter enabled + 註 hook + 收集 skill_dirs / mcp_servers。

    Caller 拿到 `skill_dirs` 後,建 SkillTool 時傳給 `load_all_skills(extra_dirs=...)`;
    拿到 `mcp_servers` 後,自行 connect(McpManager)。

    Args:
        settings: settings.json 內容(讀 `enabledPlugins`)
        hook_registry: 要註冊 hook 到的 registry
        web_only: True → 拒絕 shell command hook(只允許 webhook)
        extra_roots: 額外 plugin 根目錄

    Returns:
        PluginLoadResult
    """
    roots = default_plugin_roots() + (extra_roots or [])
    discovered = builtin_plugins() + discover_plugins(roots)

    enabled = get_enabled_plugins(settings)
    loaded: list[PluginManifest] = []
    skill_dirs: list[Path] = []
    mcp_servers: dict[str, dict[str, Any]] = {}
    hooks_registered = 0

    for plugin in discovered:
        if plugin.name not in enabled:
            continue

        # hooks
        if plugin.hooks:
            n = register_frontmatter_hooks(
                plugin.hooks,
                hook_registry,
                web_only=web_only,
                source=f"plugin:{plugin.name}",
            )
            hooks_registered += n

        # skill dirs
        if plugin.source is not None:
            for rel in plugin.skills:
                skill_path = plugin.source / rel
                # skill 條目可能是檔(.md)或目錄;統一加目錄(parent of file 或 dir 自己)
                if skill_path.is_dir():
                    skill_dirs.append(skill_path)
                elif skill_path.parent.is_dir():
                    skill_dirs.append(skill_path.parent)

        # mcp servers
        for srv_name, cfg in plugin.mcp_servers.items():
            namespaced = f"{plugin.name}__{srv_name}"
            if isinstance(cfg, dict):
                mcp_servers[namespaced] = cfg

        loaded.append(plugin)

    # dedup skill_dirs(保序)
    seen: set[str] = set()
    deduped_skill_dirs: list[Path] = []
    for d in skill_dirs:
        key = str(d)
        if key in seen:
            continue
        seen.add(key)
        deduped_skill_dirs.append(d)

    return PluginLoadResult(
        loaded=loaded,
        skill_dirs=deduped_skill_dirs,
        mcp_servers=mcp_servers,
        hooks_registered=hooks_registered,
    )


# ─── enable / disable(寫 settings.json)──────────────────────────────────


def enable_plugin(settings: dict[str, Any], plugin_name: str) -> dict[str, Any]:
    """加 plugin_name 進 enabledPlugins(in-place + return)。"""
    raw = settings.get("enabledPlugins", [])
    if not isinstance(raw, list):
        raw = []
    if plugin_name not in raw:
        raw.append(plugin_name)
    settings["enabledPlugins"] = raw
    return settings


def disable_plugin(settings: dict[str, Any], plugin_name: str) -> dict[str, Any]:
    """從 enabledPlugins 移掉 plugin_name(in-place + return)。"""
    raw = settings.get("enabledPlugins", [])
    if isinstance(raw, list) and plugin_name in raw:
        raw.remove(plugin_name)
    settings["enabledPlugins"] = raw
    return settings
