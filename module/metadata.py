# -*- coding: utf-8 -*-
"""
Collect the raw generation metadata of an image: text chunks first,
stealth pnginfo (pixel LSBs) only when no text chunk holds parameters.
"""
from __future__ import annotations

from typing import Optional, Tuple

from PIL import Image

from module.stealth import StealthInfo, find_stealth, stealth_to_info

# Text chunk keys that carry generation parameters (WebUI / ComfyUI / NovelAI)
PARAMETER_KEYS = ("parameters", "prompt", "Comment")


def has_parameters(data: dict) -> bool:
    return any(key in data for key in PARAMETER_KEYS)


def read_image_metadata(image: Image.Image) -> Tuple[dict, Optional[StealthInfo]]:
    """Return (metadata dict, stealth info if the metadata came from pixels)."""
    # Text chunks written after the image data only show up in info after a full load
    image.load()
    data = dict(image.info)
    if has_parameters(data):
        return data, None

    stealth = find_stealth(image)
    if stealth:
        data.update(stealth_to_info(stealth.text))
    return data, stealth
