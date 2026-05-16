"""Phase 31-D bug debug:Cowork sidecar 路徑 vision 是否真打通。

Spawn sidecar subprocess、送 conversation.send 帶 image attachment(base64
紅色 64x64 PNG)、驗 model 回應提到 "red"。

需要 ANTHROPIC_API_KEY,沒設就 skip。
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tempfile

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


def _red_png_base64() -> str:
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    img = Image.new("RGB", (64, 64), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.mark.parametrize("provider,model", [
    ("anthropic", "claude-haiku-4-5"),
    ("openai", "gpt-4o-mini"),  # User reported case — UI default
])
def test_sidecar_passes_attachment_to_model(provider: str, model: str) -> None:
    """End-to-end:sidecar → SDK → provider → response 應提到 red。"""
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    img_b64 = _red_png_base64()

    with tempfile.TemporaryDirectory(prefix="cowork-vision-") as data_dir:
        env = dict(os.environ)
        env["ORION_COWORK_DATA_DIR"] = data_dir

        create = json.dumps({
            "id": "c",
            "method": "conversation.create",
            "params": {"provider": provider, "model": model},
        }) + "\n"
        # send 完整 turn:含 prompt + 1 attachment(紅色 PNG)
        send = json.dumps({
            "id": "s",
            "method": "conversation.send",
            "params": {
                "session_id": "PLACEHOLDER",
                "prompt": "What color is this image? One word answer.",
                "attachments": [{
                    "media_type": "image/png",
                    "data": img_b64,
                }],
            },
        })

        # Phase 1:create → 拿 sid
        proc = subprocess.run(
            [sys.executable, "-m", "orion_cowork_sidecar"],
            input=create,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        frames = [json.loads(line) for line in proc.stdout.strip().split("\n") if line]
        created = next(f for f in frames if f.get("id") == "c")
        assert created["event"] == "conversation_created", f"create failed: {created}"
        sid = created["data"]["session_id"]

        # Phase 2:send 帶圖 — 用真實 sid
        send_real = send.replace("PLACEHOLDER", sid)
        proc = subprocess.run(
            [sys.executable, "-m", "orion_cowork_sidecar"],
            input=send_real,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        frames = [json.loads(line) for line in proc.stdout.strip().split("\n") if line]

        # 收集所有 text_delta
        text_chunks: list[str] = []
        errors: list[dict] = []
        for f in frames:
            if f.get("event") == "text_delta":
                text_chunks.append(((f.get("data") or {}).get("text") or ""))
            if f.get("error"):
                errors.append(f)

        assert not errors, f"sidecar errors: {errors}"
        final = "".join(text_chunks).lower()
        # 模型應該識別紅色
        assert "red" in final or "紅" in final, (
            f"model didn't see red image — got: {final!r} "
            f"(attachment likely dropped between sidecar and SDK)"
        )
