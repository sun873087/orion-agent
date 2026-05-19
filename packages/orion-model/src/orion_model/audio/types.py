"""Audio shared result types。Dataclass + dict-like 對外 serialize。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TranscribeResult:
    text: str
    provider: str
    model: str
    duration_seconds: float | None
    cost_usd: float | None


@dataclass
class SynthesizeResult:
    audio_bytes: bytes
    mime_type: str
    provider: str
    model: str
    voice: str
    char_count: int
    cost_usd: float


__all__ = ["SynthesizeResult", "TranscribeResult"]
