"""Plugin manifest 型別。

`plugin.json` 範例:

```json
{
  "name": "github-tools",
  "version": "0.1.0",
  "description": "GitHub PR/issue 工具",
  "skills": ["skills/review-pr.md", "skills/triage-issues.md"],
  "hooks": [
    {"event": "PostToolUse",
     "matcher": {"tool_name": "Bash"},
     "command": "node hooks/audit.js"}
  ],
  "mcp_servers": {
    "github": {"command": "node", "args": ["mcp/server.js"]}
  }
}
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PluginManifest:
    """已 parse 的 plugin manifest。"""

    name: str
    version: str = "0.0.0"
    description: str = ""
    skills: list[str] = field(default_factory=list)
    """relative path(對於 source 目錄)"""
    hooks: list[dict[str, Any]] = field(default_factory=list)
    """同 settings.json hook 條目格式"""
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    """server_name → mcp config dict"""
    source: Path | None = None
    """plugin 根目錄。"""
