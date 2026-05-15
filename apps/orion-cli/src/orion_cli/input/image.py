"""Image input — Phase 11。

純標準庫 helpers(不依賴 PIL):base64 encode、size limit、副檔名 → media_type。
壓縮(超過 5 MB / 2048px)留 Phase 11c 加 Pillow。

Anthropic vision API 接受 base64 source(無 size hard limit,但建議 < 5MB / 8000px),
本檔提供 size 警告但不強制壓縮。
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from orion_cli.input.process_input import ImageAttachment

_EXT_TO_MEDIA: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB(警告 threshold)


class ImageTooLargeError(ValueError):
    """圖片超過 size limit。"""


def media_type_for_path(path: str | Path) -> str:
    """副檔名 → media_type;不認得 fallback `image/png`。"""
    p = Path(path)
    return _EXT_TO_MEDIA.get(p.suffix.lower(), "image/png")


def encode_image_bytes(
    data: bytes,
    media_type: str,
    *,
    max_bytes: int = _MAX_IMAGE_BYTES,
) -> ImageAttachment:
    """raw bytes → ImageAttachment(base64)。超 max_bytes raise。"""
    if len(data) > max_bytes:
        raise ImageTooLargeError(
            f"image is {len(data)} bytes, exceeds {max_bytes} bytes limit",
        )
    encoded = base64.b64encode(data).decode("ascii")
    return ImageAttachment(media_type=media_type, data=encoded)


def encode_image_file(
    path: str | Path,
    *,
    max_bytes: int = _MAX_IMAGE_BYTES,
) -> ImageAttachment:
    """檔案 → ImageAttachment。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    return encode_image_bytes(p.read_bytes(), media_type_for_path(p), max_bytes=max_bytes)


def decode_data_url(data_url: str) -> ImageAttachment:
    """parse `data:image/png;base64,XXXXX` → ImageAttachment。

    前端 paste 圖片的 dataURL 格式。
    """
    if not data_url.startswith("data:"):
        raise ValueError("not a data URL")
    head, _, body = data_url[5:].partition(",")
    media_part, _, encoding = head.partition(";")
    if encoding != "base64" or not media_part.startswith("image/"):
        raise ValueError(f"unsupported data URL: {head!r}")
    # 簡單 sanity:body 應為合法 base64
    try:
        base64.b64decode(body, validate=True)
    except (ValueError, binascii.Error) as e:
        raise ValueError(f"invalid base64 in data URL: {e}") from e
    return ImageAttachment(media_type=media_part, data=body)


def to_content_block(image: ImageAttachment) -> dict[str, object]:
    """ImageAttachment → Anthropic vision API ContentBlock dict。"""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": image.media_type,
            "data": image.data,
        },
    }
