"""PII-safe diagnostic — Phase 9。對應 TS diagnosticTracking.ts。

提供 `redact_pii(text)` 函式 + `redact_processor` structlog processor。
非完美 redact(無 NER),但能擋住常見 email / phone / SSN / credit card,
讓觀測性 log / Otel attribute 不會直接外洩使用者資料。

Caller 接 structlog 時把本 processor 加進 chain:

```python
import structlog
from orion_sdk.telemetry.diagnostic import redact_processor

structlog.configure(processors=[..., redact_processor, ...])
```

或用 `safe_log_payload(dict)` 一次 redact 整 dict 的 sensitive keys。
"""

from __future__ import annotations

import re
from typing import Any

# 常見 PII patterns(英美格式為主;不打算 cover 全球)
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "phone_intl": re.compile(r"\+\d{1,3}[\s-]?\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}"),
    "phone_us": re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
    # API key 樣態(覆蓋 Anthropic / OpenAI 的常見 prefix)
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai_key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
}


def redact_pii(text: str) -> str:
    """把已知 PII pattern 換成 `[REDACTED_<TYPE>]`。"""
    for name, pattern in _PII_PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{name.upper()}]", text)
    return text


# 哪些 dict key 被視為「使用者輸入」,自動 deep-redact
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "user_input",
        "prompt",
        "message",
        "content",
        "command",
        "url",
        "path",
        "query",
        "body",
        "raw_text",
    }
)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, dict):
        return safe_log_payload(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


def safe_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """deep-clone + redact dict 的 sensitive 欄位。

    只對 _SENSITIVE_KEYS 內的 key 跑 PII pattern;其他欄位保留(但會 recurse 進 nested dict)。
    """
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in _SENSITIVE_KEYS:
            out[k] = _redact_value(v)
        elif isinstance(v, dict):
            out[k] = safe_log_payload(v)
        elif isinstance(v, list):
            out[k] = [safe_log_payload(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


def redact_processor(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor 形式 — 直接掛進 `processors=[...]`。

    對 _SENSITIVE_KEYS 自動 redact。回傳 mutated event_dict(structlog convention)。
    """
    for key in list(event_dict.keys()):
        if key in _SENSITIVE_KEYS:
            event_dict[key] = _redact_value(event_dict[key])
        elif isinstance(event_dict[key], dict):
            event_dict[key] = safe_log_payload(event_dict[key])
    return event_dict
