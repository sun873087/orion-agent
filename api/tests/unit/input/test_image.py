"""image helpers — encode / data URL parse / size limit。"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from orion_agent.input.image import (
    ImageTooLargeError,
    decode_data_url,
    encode_image_bytes,
    encode_image_file,
    media_type_for_path,
    to_content_block,
)


def test_media_type_for_path() -> None:
    assert media_type_for_path("a.png") == "image/png"
    assert media_type_for_path("a.JPG") == "image/jpeg"
    assert media_type_for_path("a.jpeg") == "image/jpeg"
    assert media_type_for_path("a.webp") == "image/webp"
    assert media_type_for_path("a.unknown") == "image/png"  # fallback


def test_encode_image_bytes() -> None:
    raw = b"fake image data"
    img = encode_image_bytes(raw, "image/png")
    decoded = base64.b64decode(img.data)
    assert decoded == raw
    assert img.media_type == "image/png"


def test_encode_image_bytes_too_large() -> None:
    raw = b"x" * 100
    with pytest.raises(ImageTooLargeError):
        encode_image_bytes(raw, "image/png", max_bytes=50)


def test_encode_image_file(tmp_path: Path) -> None:
    p = tmp_path / "test.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    img = encode_image_file(p)
    assert img.media_type == "image/png"
    assert base64.b64decode(img.data).startswith(b"\x89PNG")


def test_encode_image_file_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        encode_image_file(tmp_path / "no_such.png")


def test_decode_data_url() -> None:
    raw = b"hello"
    encoded = base64.b64encode(raw).decode("ascii")
    img = decode_data_url(f"data:image/png;base64,{encoded}")
    assert img.media_type == "image/png"
    assert base64.b64decode(img.data) == raw


def test_decode_data_url_invalid() -> None:
    with pytest.raises(ValueError):
        decode_data_url("not a data url")
    with pytest.raises(ValueError):
        decode_data_url("data:text/plain;base64,xx")  # 不是 image
    with pytest.raises(ValueError):
        decode_data_url("data:image/png;hex,zzz")  # 不是 base64


def test_to_content_block() -> None:
    img = encode_image_bytes(b"x", "image/png")
    block = to_content_block(img)
    assert block["type"] == "image"
    src = block["source"]
    assert src["type"] == "base64"  # type: ignore[index]
    assert src["media_type"] == "image/png"  # type: ignore[index]
