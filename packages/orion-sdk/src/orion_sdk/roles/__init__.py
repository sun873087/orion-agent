"""Pane roles for multi-pane collaboration。

每 role 一個 markdown 檔:
```
roles/<name>/ROLE.md  ← frontmatter + body
```

Frontmatter 欄位:
- `name`(預設用資料夾名)
- `description`:UI 顯示用一句話
- `default_disabled_tools`:逗號分隔工具名(如 `Edit,Write,Bash`),建立 pane 時自動 disable
- `default_permission_mode`:`ask` / `act`(可選;不設 = 用 user 設定預設)

Body = prompt addendum,append 進 system prompt。

Source 優先序(後者覆蓋前者):
1. bundled(`orion_sdk/roles/bundled/`)
2. user(`~/.orion/users/<u>/roles/`)
"""

from __future__ import annotations

from orion_sdk.roles.loader import Role, load_all_roles, load_roles_dir

__all__ = ["Role", "load_all_roles", "load_roles_dir"]
