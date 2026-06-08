from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def load_rgb_image(path: Path) -> np.ndarray:
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported image format: {path.suffix}")

    try:
        with Image.open(path) as img:
            fixed = ImageOps.exif_transpose(img).convert("RGB")
            return np.array(fixed, dtype=np.uint8)
    except UnidentifiedImageError as exc:
        raise ValueError(f"Invalid image file: {path}") from exc
