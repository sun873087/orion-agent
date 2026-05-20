"""provider failover skeleton。

Upstream 429 / 5xx 自動 retry 另一 provider 的對應 model(若 routing alias
有定義 fallback chain)。例:
    user 設 "auto" → 主 gpt-5 / fallback claude-sonnet-4-6
    proxy 收 429 from openai → 自動改打 anthropic claude-sonnet-4-6

當前 skeleton 的 transparent reverse 沒做 model 翻譯,
所以 failover 在跨 provider 場景需要 wire format 互轉,複雜。
此 module 先放 fallback chain 解析邏輯,reverse_proxy 端日後接入。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FallbackTarget:
    provider: str
    model: str


# 全域 fallback chain(可由 admin 編進 routing_aliases 表延伸)。
# X / 32 還沒接入 reverse_proxy。
_DEFAULT_CHAINS: dict[tuple[str, str], list[FallbackTarget]] = {
    ("openai", "gpt-5"): [FallbackTarget("anthropic", "claude-sonnet-4-6")],
    ("openai", "gpt-5-mini"): [FallbackTarget("anthropic", "claude-haiku-4-5")],
    ("anthropic", "claude-sonnet-4-6"): [FallbackTarget("openai", "gpt-5")],
    ("anthropic", "claude-haiku-4-5"): [FallbackTarget("openai", "gpt-5-mini")],
}


def get_fallback_chain(provider: str, model: str) -> list[FallbackTarget]:
    """Return ordered list of (provider, model) to try after primary fails。"""
    return list(_DEFAULT_CHAINS.get((provider, model), []))


def should_failover(status_code: int) -> bool:
    """Failover trigger:rate-limit / upstream 5xx。401/403 不切(那是 client 問題)。"""
    return status_code == 429 or 500 <= status_code < 600


__all__ = ["FallbackTarget", "get_fallback_chain", "should_failover"]
