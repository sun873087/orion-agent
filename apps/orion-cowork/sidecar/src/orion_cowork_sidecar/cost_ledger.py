"""Cost ledger — per-session 收集每筆 LLM call 的 token usage,按 origin 分類算 USD。

**問題場景**:Cowork 的 cumulative cost 原本只算 `conv.stats`(主對話 LLM call),
所有不走 `conv.send` 的 LLM call(本 session 加的 5 個 cheap LLM feature、
AgentTool 子 agent、auto-compact 摘要)全部漏算。User 在意成本就會被誤導。

**設計**:per-session ledger 收集 N 個 origin 的 token 累計,單一地方算 USD。
所有 LLM call 完都應該往 ledger record 一筆。`_compute_cumulative_cost` 改從
ledger 算。Ledger 序列化成 JSON 存進 `cowork_session_ext.cost_breakdown_json`,
sidecar restart 跨 process 也能 hydrate 回來。

**Origin label 約定**(新增請更新):
- `chat` — Conversation.send 主對話 LLM call
- `subagent` — AgentTool spawn 出來的子 agent 內部 LLM call(merge 回 parent)
- `compact` — auto-compact 摘要 LLM call(SDK 內部跑,目前 SDK 沒 emit usage,
  暫 known limitation)
- `title` — 自動 session title 生成
- `follow_ups` — 對話後續建議句
- `explain` — Banner / tool error 的「不懂?讓 AI 解釋」按鈕
- `summarize` — 訊息一鍵摘要
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from orion_model.pricing import get_pricing


# 已知 origin label — 主要給 docs / type hints 參考,實際運行不強制
# (新加 LLM call feature 直接 record 任意字串即可,UI 顯示時對未知 label
# fallback 「其他」)
KNOWN_ORIGINS: tuple[str, ...] = (
    "chat",
    "subagent",
    "compact",
    "title",
    "follow_ups",
    "explain",
    "summarize",
)


@dataclass
class OriginBucket:
    """單一 origin 在這 session 的累計 usage + cost。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    count: int = 0
    # 顯示用 — 最後一次 record 用的 provider / model(同 origin 跨 model
    # 場景少;若混用 UI 顯最後一個就好)
    provider: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "count": self.count,
            "provider": self.provider,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OriginBucket:
        return cls(
            input_tokens=int(d.get("input_tokens", 0) or 0),
            output_tokens=int(d.get("output_tokens", 0) or 0),
            cache_read_tokens=int(d.get("cache_read_tokens", 0) or 0),
            cache_creation_tokens=int(d.get("cache_creation_tokens", 0) or 0),
            cost_usd=float(d.get("cost_usd", 0.0) or 0.0),
            count=int(d.get("count", 0) or 0),
            provider=str(d.get("provider", "") or ""),
            model=str(d.get("model", "") or ""),
        )


@dataclass
class CostLedger:
    """Per-session ledger,buckets by origin。In-memory 收集,DB 持久化 JSON。"""

    buckets: dict[str, OriginBucket] = field(default_factory=dict)

    def record(
        self,
        origin: str,
        *,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """把一次 LLM call 的 usage 加進 ledger。Tokens 0 也記(count + 1),
        知道「這 origin 跑過幾次」對 user 透明度有用。

        Pricing 失敗 silent:cost 算 0(不該炸記帳)。
        """
        bucket = self.buckets.get(origin)
        if bucket is None:
            bucket = OriginBucket(provider=provider, model=model)
            self.buckets[origin] = bucket
        bucket.input_tokens += int(input_tokens or 0)
        bucket.output_tokens += int(output_tokens or 0)
        bucket.cache_read_tokens += int(cache_read_tokens or 0)
        bucket.cache_creation_tokens += int(cache_creation_tokens or 0)
        bucket.count += 1
        bucket.provider = provider
        bucket.model = model
        try:
            p = get_pricing(provider, model)
            input_price = p.get("input", 0.0)
            output_price = p.get("output", 0.0)
            cache_read_price = p.get("cache_read", input_price)
            cache_creation_price = p.get("cache_creation", input_price)
            delta = (
                (input_tokens or 0) * input_price
                + (output_tokens or 0) * output_price
                + (cache_read_tokens or 0) * cache_read_price
                + (cache_creation_tokens or 0) * cache_creation_price
            ) / 1_000_000
            bucket.cost_usd += delta
        except Exception: # noqa: BLE001
            # Pricing miss(catalog 沒這 model)— 記 0,不擾 user
            pass

    def total_usd(self) -> float:
        return round(sum(b.cost_usd for b in self.buckets.values()), 6)

    def breakdown(self) -> dict[str, dict[str, Any]]:
        """回 {origin: bucket_dict},給 RPC / DB persistence 用。"""
        return {origin: bucket.to_dict() for origin, bucket in self.buckets.items()}

    def to_json(self) -> str:
        return json.dumps(self.breakdown(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None) -> CostLedger:
        """從 DB JSON hydrate。空 / 解析失敗回空 ledger,不擋啟動。"""
        if not raw:
            return cls()
        try:
            d = json.loads(raw)
            if not isinstance(d, dict):
                return cls()
            return cls(
                buckets={
                    origin: OriginBucket.from_dict(bucket)
                    for origin, bucket in d.items()
                    if isinstance(bucket, dict)
                }
            )
        except Exception: # noqa: BLE001
            return cls()
