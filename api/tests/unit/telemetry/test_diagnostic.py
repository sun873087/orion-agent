"""diagnostic.redact_pii + safe_log_payload + redact_processor。"""

from __future__ import annotations

from orion_agent.telemetry.diagnostic import (
    redact_pii,
    redact_processor,
    safe_log_payload,
)


def test_redact_email() -> None:
    out = redact_pii("contact us at john.doe+spam@example.com please")
    assert "john.doe" not in out
    assert "[REDACTED_EMAIL]" in out


def test_redact_us_phone() -> None:
    out = redact_pii("call 415-555-1234 today")
    assert "415-555-1234" not in out
    assert "[REDACTED_PHONE_US]" in out


def test_redact_ssn() -> None:
    out = redact_pii("SSN: 123-45-6789")
    assert "123-45-6789" not in out
    assert "[REDACTED_SSN]" in out


def test_redact_credit_card() -> None:
    out = redact_pii("card 4111 1111 1111 1111")
    assert "4111" not in out


def test_redact_anthropic_key() -> None:
    out = redact_pii("auth=sk-ant-abc123def456ghi789jkl012")
    assert "sk-ant-abc" not in out
    assert "[REDACTED_ANTHROPIC_KEY]" in out


def test_redact_openai_key() -> None:
    out = redact_pii("auth=sk-proj-abc123def456ghi789jkl012")
    assert "[REDACTED_OPENAI_KEY]" in out


def test_safe_log_payload_redacts_known_keys() -> None:
    p = {
        "user_input": "email me at a@b.com",
        "tool_input": {"command": "echo a@b.com"},
        "non_sensitive": "a@b.com",  # 不在 sensitive list,不 redact 字串本身
    }
    out = safe_log_payload(p)
    assert "[REDACTED_EMAIL]" in out["user_input"]
    # non-sensitive 字串原樣
    assert out["non_sensitive"] == "a@b.com"


def test_safe_log_payload_recurses() -> None:
    p = {"meta": {"command": "curl http://x; ssh user@host.com"}}
    out = safe_log_payload(p)
    assert "[REDACTED_EMAIL]" in out["meta"]["command"]


def test_redact_processor_mutates_event_dict() -> None:
    ev = {"event": "tool_call", "user_input": "send to alice@b.com"}
    out = redact_processor(None, "info", ev)
    assert "[REDACTED_EMAIL]" in out["user_input"]
