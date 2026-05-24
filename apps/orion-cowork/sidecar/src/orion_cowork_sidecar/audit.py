"""Per-turn audit cache — 記住「本 turn LLM 真實看到什麼」,給 A1「為什麼這樣
回答」UI 用。

**動機**:User 信任 Orion 必須能看到「Orion 用了什麼回答我」— 哪些 system
instruction / soul.md / tools / model 進去了。但 LLM 真正用的 effective_system_prompt
是 SDK 內部組裝(static prefix + per-turn memory inject),sidecar 看不到完整版。

**折衷做法**:audit 只存 sidecar 端**已知**的部分:
- `conv.system_prompt`(sidecar 在 `_build_conversation` 內組,已含 soul /
  user_instructions / project instructions / paths)— 約 80-90% 的「指令面」內容
- `conv.tools` 列表(本 turn 可用 tools)
- provider / model + 本 turn token delta + cost(從 ledger 算)

SDK 自動 inject 的 memory ranker / git_status / per_turn_text 暫不 audit
(需要 SDK 暴露 hook,留給未來 iteration)。對話歷史 messages 不存(renderer
端已有完整 `messagesBySession`,modal 直接讀;sidecar 不必雙寫)。

**Dedup 設計**:同 session 內 `system_prompt` + `tools` 跨 turn 幾乎不變
(只在 user 改 settings / 切 project / 更新 soul.md 才會變)。每 turn 完整存
會把 SQLite 撐爆(100 turn × ~8KB ≈ 1MB per session)。

改用 **content-addressed dedup**:`AuditStore` 內有 `prompts: {hash → str}`
跟 `tool_sets: {hash → list}` 兩張表,每個 entry 只存 hash 指過去。Ring buffer
evict 一筆時 GC 沒人引用的 hash。實測 100 turn 從 ~1MB 壓到 ~30KB。

**Wire messages buffer**(A2):user Settings 可調保留最近 N 個 turn 的 sidecar
端 `conv.state_messages` snapshot(預設 N=1,範圍 0-20)。**不是 100% 的真實
wire**:SDK 在 `conv.send` 內會對最後一條 user msg 跑 `inject_per_turn_into_user_message`
注入 memory ranker / git_status / per_turn_text 結果(`augmented_user_msg`),
sidecar 看到的 `conv.state_messages` 不含這段 inject。**對齊度約 95%**
— 對話內容 / tool_use / tool_result blocks 100% 對 wire,僅缺最後一輪 user msg
的 per-turn auto-inject 增補。Modal UI 已附 disclaimer 提示 user 這點。

dedup 不適用(每 turn messages list 都不一樣,hash 不會 match),改用獨立 ring
buffer,maxlen 從 send 帶過來。Entry 用 `wire_seq` 對應到 buffer 內的 sequence
number — 因為 buffer evict 不影響 entry,只是 lookup 時可能 miss(那筆 wire 已
被擠掉,renderer 走 fallback 顯 messagesBySession,UI 端標 approximate)。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolEntry:
    """Tool 在 audit 用的精簡版 — name + 一句 description(截 200 字)。完整 schema
    不放(太長,user 不需要看)。"""

    name: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ToolEntry:
        return cls(
            name=str(d.get("name", "") or ""),
            description=str(d.get("description", "") or ""),
        )


@dataclass
class AuditEntry:
    """單 turn 的 audit ref。system_prompt / tools 走 dedupe 表 hash 對應,本身
    只記 turn-specific 資訊(token / cost / turn_index 等)+ wire_seq 指 wire
    messages buffer 內的 snapshot(若有)。"""

    turn_index: int
    timestamp: float
    message_index: int
    """`conv.state_messages` 內最後一個 assistant 的 position(legacy,backward
    compat 用;renderer 端對應有 mismatch)。"""
    system_prompt_hash: str
    tools_hash: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    # A2 wire messages — sequence number 指向 wire_buffer 內某 snapshot。
    # -1 = 該 turn 沒存 wire(N=0 設定 / buffer evict / N=1 但有新 turn 進來
    # 把這筆擠掉)。renderer 拿 expanded audit 時若 wire_messages 為 null,
    # fallback 顯 messagesBySession。
    wire_seq: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "timestamp": self.timestamp,
            "message_index": self.message_index,
            "system_prompt_hash": self.system_prompt_hash,
            "tools_hash": self.tools_hash,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "wire_seq": self.wire_seq,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditEntry:
        return cls(
            turn_index=int(d.get("turn_index", 0) or 0),
            timestamp=float(d.get("timestamp", 0.0) or 0.0),
            message_index=int(d.get("message_index", -1) or -1),
            system_prompt_hash=str(d.get("system_prompt_hash", "") or ""),
            tools_hash=str(d.get("tools_hash", "") or ""),
            provider=str(d.get("provider", "") or ""),
            model=str(d.get("model", "") or ""),
            input_tokens=int(d.get("input_tokens", 0) or 0),
            output_tokens=int(d.get("output_tokens", 0) or 0),
            cache_read_tokens=int(d.get("cache_read_tokens", 0) or 0),
            cache_creation_tokens=int(d.get("cache_creation_tokens", 0) or 0),
            cost_usd=float(d.get("cost_usd", 0.0) or 0.0),
            wire_seq=int(d.get("wire_seq", -1) if d.get("wire_seq") is not None else -1),
        )


def _hash16(s: str) -> str:
    """SHA256 截前 16 字當 dedup key — collision rate 對 100 turn 規模可忽略。"""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


@dataclass
class AuditStore:
    """Per-session audit:dedup 大欄位(system_prompt / tools),每 turn 只記 ref +
    token usage。Ring buffer 最近 100 turns,DB JSON 持久化跨重啟。

    Wire messages(A2):獨立 ring buffer,maxlen 從 settings 來,user 可控 0-20。
    每筆 entry 用 monotonic `wire_seq` 對應 buffer 內某 snapshot;buffer evict
    後 entry.wire_seq 對不上就視為 「該 turn wire 不在」。
    """

    prompts: dict[str, str] = field(default_factory=dict)
    tool_sets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    entries: deque[AuditEntry] = field(default_factory=lambda: deque(maxlen=100))
    maxlen: int = 100
    # Wire messages buffer — list of (seq, messages_snapshot)。Maxlen 動態調(
    # user settings 變動時就 resize)。
    wire_buffer: list[tuple[int, list[dict[str, Any]]]] = field(default_factory=list)
    wire_maxlen: int = 1
    next_wire_seq: int = 0

    def __post_init__(self) -> None:
        if self.entries.maxlen != self.maxlen:
            self.entries = deque(self.entries, maxlen=self.maxlen)

    def set_wire_maxlen(self, n: int) -> None:
        """調 wire buffer 上限。n=0 表示完全不存 wire。Trim 多餘的舊 snapshot。"""
        n = max(0, min(20, int(n)))
        self.wire_maxlen = n
        # Trim 舊的(從前面砍)
        while len(self.wire_buffer) > n:
            self.wire_buffer.pop(0)

    def record_wire(self, messages: list[dict[str, Any]]) -> int:
        """把該 turn 真實送 LLM 的 messages snapshot 寫進 buffer,回新 seq。
        N=0 時不存,回 -1。Buffer 滿時 FIFO evict。"""
        if self.wire_maxlen <= 0:
            return -1
        seq = self.next_wire_seq
        self.next_wire_seq += 1
        self.wire_buffer.append((seq, messages))
        while len(self.wire_buffer) > self.wire_maxlen:
            self.wire_buffer.pop(0)
        return seq

    def get_wire(self, wire_seq: int) -> list[dict[str, Any]] | None:
        """從 buffer 找對應 seq 的 snapshot,沒找到回 None(已 evict)。"""
        if wire_seq < 0:
            return None
        for seq, msgs in self.wire_buffer:
            if seq == wire_seq:
                return msgs
        return None

    def record(
        self,
        *,
        turn_index: int,
        message_index: int,
        system_prompt: str,
        tools: list[ToolEntry],
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
        cost_usd: float,
        wire_seq: int = -1,
    ) -> None:
        """Append 新 audit entry,system_prompt / tools 自動 hash + dedup。
        Ring buffer 滿時前一筆被 evict,順手 GC 沒人引用的 hash。"""
        sp_hash = _hash16(system_prompt or "")
        if sp_hash not in self.prompts:
            self.prompts[sp_hash] = system_prompt or ""

        tools_serialized = [t.to_dict() for t in tools]
        # sort_keys 讓相同 tool set 產生相同 hash(避免 dict 順序變動誤判 diff)
        tools_str = json.dumps(tools_serialized, sort_keys=True, ensure_ascii=False)
        tools_hash = _hash16(tools_str)
        if tools_hash not in self.tool_sets:
            self.tool_sets[tools_hash] = tools_serialized

        # Ring buffer evict — 在 append 前看是否會丟舊筆,事後 GC
        will_evict = len(self.entries) >= self.maxlen
        self.entries.append(AuditEntry(
            turn_index=turn_index,
            timestamp=time.time(),
            message_index=message_index,
            system_prompt_hash=sp_hash,
            tools_hash=tools_hash,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            wire_seq=wire_seq,
        ))
        if will_evict:
            self._gc_unreferenced()

    def _gc_unreferenced(self) -> None:
        """掃 entries 內仍引用的 hash,沒人引用的從 prompts / tool_sets 移除。"""
        used_sp = {e.system_prompt_hash for e in self.entries}
        used_tools = {e.tools_hash for e in self.entries}
        for h in list(self.prompts):
            if h not in used_sp:
                del self.prompts[h]
        for h in list(self.tool_sets):
            if h not in used_tools:
                del self.tool_sets[h]

    def latest_expanded(self) -> dict[str, Any] | None:
        if not self.entries:
            return None
        return self._expand(self.entries[-1])

    def find_by_turn_index(self, turn_index: int) -> dict[str, Any] | None:
        """找對應 turn 的完整 audit(自動把 hash 展開回完整 system_prompt / tools)。"""
        for e in reversed(self.entries):
            if e.turn_index == turn_index:
                return self._expand(e)
        return None

    def find_by_message_index(self, message_index: int) -> dict[str, Any] | None:
        """Legacy lookup — backward compat,renderer 端用 turn_index 比較準。"""
        for e in reversed(self.entries):
            if e.message_index == message_index:
                return self._expand(e)
        return None

    def _expand(self, e: AuditEntry) -> dict[str, Any]:
        """把 ref entry 加上 dedup 表內的完整 system_prompt / tools / wire messages,
        給 RPC 回出去。wire_messages 為 null 表示沒存(N=0 或被 evict),renderer
        要 fallback 顯 messagesBySession。"""
        wire = self.get_wire(e.wire_seq)
        return {
            "turn_index": e.turn_index,
            "timestamp": e.timestamp,
            "message_index": e.message_index,
            "system_prompt": self.prompts.get(e.system_prompt_hash, ""),
            "tools": list(self.tool_sets.get(e.tools_hash, [])),
            "wire_messages": wire,
            "provider": e.provider,
            "model": e.model,
            "input_tokens": e.input_tokens,
            "output_tokens": e.output_tokens,
            "cache_read_tokens": e.cache_read_tokens,
            "cache_creation_tokens": e.cache_creation_tokens,
            "cost_usd": round(e.cost_usd, 6),
        }

    def to_json(self) -> str:
        return json.dumps({
            "prompts": self.prompts,
            "tool_sets": self.tool_sets,
            "entries": [e.to_dict() for e in self.entries],
            "wire_buffer": [{"seq": s, "messages": m} for s, m in self.wire_buffer],
            "wire_maxlen": self.wire_maxlen,
            "next_wire_seq": self.next_wire_seq,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None, maxlen: int = 100) -> AuditStore:
        store = cls(maxlen=maxlen)
        if not raw:
            return store
        try:
            d = json.loads(raw)
            if not isinstance(d, dict):
                return store
            raw_prompts = d.get("prompts", {})
            if isinstance(raw_prompts, dict):
                store.prompts = {str(k): str(v) for k, v in raw_prompts.items()}
            raw_tools = d.get("tool_sets", {})
            if isinstance(raw_tools, dict):
                store.tool_sets = {
                    str(k): list(v) for k, v in raw_tools.items() if isinstance(v, list)
                }
            raw_entries = d.get("entries", [])
            if isinstance(raw_entries, list):
                for item in raw_entries:
                    if isinstance(item, dict):
                        try:
                            store.entries.append(AuditEntry.from_dict(item))
                        except Exception: # noqa: BLE001
                            continue
            raw_wire = d.get("wire_buffer", [])
            if isinstance(raw_wire, list):
                for item in raw_wire:
                    if isinstance(item, dict) and "seq" in item and isinstance(item.get("messages"), list):
                        store.wire_buffer.append((int(item["seq"]), list(item["messages"])))
            wml = d.get("wire_maxlen")
            if isinstance(wml, int):
                store.wire_maxlen = max(0, min(20, wml))
            nws = d.get("next_wire_seq")
            if isinstance(nws, int):
                store.next_wire_seq = max(nws, 0)
        except Exception: # noqa: BLE001
            pass
        return store


def build_tool_entries(tools: list[Any]) -> list[ToolEntry]:
    """從 conv.tools 抽 name + description(截 200 字)。description 可能含
    long help text,modal 不需要全文。"""
    out: list[ToolEntry] = []
    for tool in tools:
        name = getattr(tool, "name", type(tool).__name__)
        desc = getattr(tool, "description", "") or ""
        if not isinstance(desc, str):
            desc = str(desc)
        # 截掉超長 description(只取第一段或前 200 字)
        first_para = desc.split("\n\n", 1)[0].strip()
        out.append(ToolEntry(name=str(name), description=first_para[:200]))
    return out
