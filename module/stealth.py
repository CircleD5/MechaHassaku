# -*- coding: utf-8 -*-
"""
Reader for "stealth pnginfo": generation parameters hidden in the least
significant bits of an image's pixels instead of in text chunks.

Format (identical across the NovelAI official reader, the A1111
sd_webui_stealth_pnginfo extension and nai-meta):
    [magic, 15 bytes][payload length in BITS, 32-bit big endian][payload]
Bits are taken column by column (x outer, y inner), one per pixel from the
alpha channel, or three per pixel (R, G, B) in RGB mode. "comp" payloads are
gzip-compressed. NovelAI appends a 32-bit FEC length after the payload,
which is not needed for display and is ignored here.
"""
from __future__ import annotations

import json
import math
import zlib
from dataclasses import dataclass
from typing import Optional

from PIL import Image

# ==================== Format ====================
MAGICS = {
    "stealth_pnginfo": ("alpha", False),
    "stealth_pngcomp": ("alpha", True),
    "stealth_rgbinfo": ("rgb", False),
    "stealth_rgbcomp": ("rgb", True),
}
SIG_BITS = 15 * 8
LEN_BITS = 32
HEADER_BITS = SIG_BITS + LEN_BITS
BITS_PER_PIXEL = {"alpha": 1, "rgb": 3}

# Guards against noise that happens to match a magic, and against gzip bombs
MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_TEXT_BYTES = 4 * 1024 * 1024

# byte -> b"0" / b"1" according to its least significant bit
_LSB_TABLE = bytes(48 + (b & 1) for b in range(256))


@dataclass
class StealthInfo:
    channel: str      # "alpha" | "rgb"
    compressed: bool
    text: str

    def describe(self) -> str:
        return f"{self.channel}{' + gzip' if self.compressed else ''}"


# ==================== Reading ====================
def find_stealth(image: Image.Image) -> Optional[StealthInfo]:
    """Return the hidden parameters of an image, or None if there are none."""
    has_alpha = "A" in image.mode or "transparency" in image.info
    channels = ("alpha", "rgb") if has_alpha else ("rgb",)
    for channel in channels:
        try:
            found = _decode_channel(image, channel)
        except Exception:
            found = None
        if found:
            return found
    return None


def _decode_channel(image: Image.Image, channel: str) -> Optional[StealthInfo]:
    width, height = image.size
    capacity = width * height * BITS_PER_PIXEL[channel]
    if capacity < HEADER_BITS:
        return None

    header = _read_bits(image, channel, HEADER_BITS)
    magic = _bits_to_bytes(header[:SIG_BITS]).decode("ascii", errors="replace")
    if MAGICS.get(magic, (None,))[0] != channel:
        return None
    compressed = MAGICS[magic][1]

    payload_bits = int(header[SIG_BITS:], 2)
    if (payload_bits <= 0 or payload_bits % 8
            or payload_bits > MAX_PAYLOAD_BYTES * 8
            or HEADER_BITS + payload_bits > capacity):
        return None

    bits = _read_bits(image, channel, HEADER_BITS + payload_bits)[HEADER_BITS:]
    payload = _bits_to_bytes(bits)
    if compressed:
        payload = _gunzip(payload)
        if payload is None:
            return None

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = payload.decode("utf-8", errors="replace")
    return StealthInfo(channel, compressed, text)


def _read_bits(image: Image.Image, channel: str, count: int) -> str:
    """Return the first `count` LSBs of the channel in column-major order as a '0'/'1' string.

    Only the leftmost columns that hold those bits are cropped and converted,
    so the cost does not grow with the size of the image.
    """
    bpp = BITS_PER_PIXEL[channel]
    width, height = image.size
    pixels = math.ceil(count / bpp)
    columns = min(width, math.ceil(pixels / height))

    region = image.crop((0, 0, columns, height))
    if channel == "alpha":
        region = region.convert("RGBA").getchannel("A")
    else:
        region = region.convert("RGB")
    # After transposing, each row of the region is one original column, top to bottom
    raw = region.transpose(Image.Transpose.TRANSPOSE).tobytes()
    return raw[:pixels * bpp].translate(_LSB_TABLE).decode("ascii")[:count]


def _bits_to_bytes(bits: str) -> bytes:
    return int(bits, 2).to_bytes(len(bits) // 8, "big") if bits else b""


def _gunzip(data: bytes) -> Optional[bytes]:
    # wbits=47 accepts both gzip and zlib headers
    decompressor = zlib.decompressobj(wbits=47)
    try:
        out = decompressor.decompress(data, MAX_TEXT_BYTES)
    except zlib.error:
        return None
    if decompressor.unconsumed_tail or not decompressor.eof:
        return None
    return out


# ==================== Interpretation ====================
def stealth_to_info(text: str) -> dict:
    """Convert hidden text into the same keys that PNG text chunks would have.

    NovelAI hides a JSON object with Description / Software / Source /
    Generation time / Comment. Everything else (A1111 extension, SwarmUI JSON)
    is the plain "parameters" string.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        data = None

    if isinstance(data, dict):
        if "Comment" in data:
            return {k: v for k, v in data.items() if v is not None}
        # Only the inner Comment object was embedded
        if "prompt" in data and ("uc" in data or "v4_prompt" in data):
            return {"Comment": data}
    return {"parameters": text}
