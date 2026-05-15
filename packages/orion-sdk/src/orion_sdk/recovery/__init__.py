"""ConversationRecovery — corrupt transcript 修復。Phase 13。

對應 TS Claude Code `src/utils/conversationRecovery.ts`。

兩種主要 corrupt 情境:
  1. JSONL 中間有半行(process 死)→ skip + 計數
  2. tool_use 寫了但對應 tool_result 沒寫 → 注 synthetic error result
     (Phase 2 `storage/resume.py:validate_and_repair_messages` 已處理;Phase 13
      的 RecoveryReport 把它的 warnings 收進來統一回給 caller)

`load_session_with_recovery(session_id) -> (SessionSnapshot, RecoveryReport)` —
是 Phase 2 `load_session` 的 production 版替身,給 resume 路徑用。
"""

from orion_sdk.recovery.transcript import (
    RecoveryReport,
    SeverelyCorruptedError,
    load_session_with_recovery,
    load_transcript_safe,
)

__all__ = [
    "RecoveryReport",
    "SeverelyCorruptedError",
    "load_session_with_recovery",
    "load_transcript_safe",
]
