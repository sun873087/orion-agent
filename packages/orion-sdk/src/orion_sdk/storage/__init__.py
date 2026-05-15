"""Storage 層 — 持久化:tool result、file history、transcript、resume。

Phase 2 範圍:
- 三層 tool result(in-memory < 100KB → disk persisted → budget-aggregated)
- ContentReplacementState(frozen / mustReapply / fresh 三類)
- File history(寫前快照)
- Session JSONL transcript
- Resume from session

對應 TS Claude Code `src/utils/toolResultStorage.ts` + `sessionStorage.ts` + 同伴。
"""

from orion_sdk.storage.paths import (
    SessionPaths,
    default_session_root,
    session_paths,
)

__all__ = [
    "SessionPaths",
    "default_session_root",
    "session_paths",
]
