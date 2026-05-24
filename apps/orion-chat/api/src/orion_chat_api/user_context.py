"""Soul(永久人格)讀寫 + 對話的 per-user system prompt 前綴。

Soul 存 `~/.orion/users/<uid>/memory/soul.md`(沿用 memory layout,跨 host 共用)。
它**不走 memory ranker** — 每次新對話固定 inject 進 system prompt 前綴,
讓模型把 user 當成認識的人。對齊 Cowork 的 soul 注入(handlers `_build_conversation`)。

注入點是 Conversation 建構時(`system_prompt` 會被 prepend 到完整 system prompt,
見 conversation.py send()),所以 soul 變更在下一個 session / cache-miss rebuild 才生效 —
與 Cowork 相同語意。
"""

from __future__ import annotations

from pathlib import Path

from orion_sdk.memory.paths import user_memory_paths

# 第一人稱框架 — 對齊 Cowork handlers.py 的 soul 注入文案。
_SOUL_FRAMING = (
    "# What you remember about this person\n\n"
    "(This is your own first-person reflection from past conversations. "
    "Speak to them naturally, the way you'd speak to someone you know.)\n\n"
)


def soul_path(user_id: str) -> Path:
    """Soul markdown 檔位置:`~/.orion/users/<uid>/memory/soul.md`。"""
    return user_memory_paths(user_id).memory_dir / "soul.md"


def read_soul(user_id: str) -> str:
    """讀 soul.md。不存在 / 讀失敗回空字串。"""
    p = soul_path(user_id)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except OSError:
        return ""


def write_soul(content: str, user_id: str) -> None:
    """寫 soul.md。空內容 = 刪檔(重置)。"""
    p = soul_path(user_id)
    if not content.strip():
        if p.exists():
            p.unlink()
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip() + "\n", encoding="utf-8")


def build_user_system_prefix(user_id: str) -> str:
    """組該 user 的 system prompt 前綴(目前 = soul)。沒內容回空字串。

    Conversation.system_prompt 不為空時會被 prepend 到完整 system prompt,
    所以回空字串時等同沒注入(不影響原本的靜態 + 動態段)。
    """
    soul = read_soul(user_id).strip()
    if not soul:
        return ""
    return _SOUL_FRAMING + soul
