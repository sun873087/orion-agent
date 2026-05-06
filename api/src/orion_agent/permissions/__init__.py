"""Permission 系統 — agent loop 在執行工具前透過 CanUseToolFn 詢問是否允許。

Phase 1 提供基礎三態(allow / ask / deny)+ always_allow 預設實作。
Phase 4 / Phase 8 會擴成完整 permission policy + 互動 UI。
"""

from orion_agent.permissions.decisions import (
    CanUseToolFn,
    PermissionDecision,
    PermissionResult,
    always_allow,
    always_deny,
)

__all__ = [
    "CanUseToolFn",
    "PermissionDecision",
    "PermissionResult",
    "always_allow",
    "always_deny",
]
