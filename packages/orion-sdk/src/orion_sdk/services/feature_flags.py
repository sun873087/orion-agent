"""Feature flags — 從環境變數 / 設定檔讀,塞進 AgentContext.feature_flags。

對應 TS `services/featureFlags.ts`(那是 Statsig)。用環境變數即可,
未來可換 Statsig / GrowthBook,但 caller code(`ctx.feature("x")`)不變。
"""

from __future__ import annotations

import os

_DEFAULT_FLAGS: dict[str, bool] = {
    # 範圍內已確定的 flag(都先 off,+ 啟用)
    "tool_concurrency": False,
    "prompt_caching": False,
    "auto_compaction": False,
    "plan_mode": False,
}


def load_feature_flags() -> dict[str, bool]:
    """讀環境變數 ORION_FF_<NAME>=1/0,合併進預設。

    範例:`ORION_FF_TOOL_CONCURRENCY=1` → `{"tool_concurrency": True, ...}`
    """
    flags = dict(_DEFAULT_FLAGS)
    for env_key, value in os.environ.items():
        if not env_key.startswith("ORION_FF_"):
            continue
        flag_name = env_key.removeprefix("ORION_FF_").lower()
        flags[flag_name] = value.strip() in ("1", "true", "True", "yes", "on")
    return flags
