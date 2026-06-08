from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_rgb_image(path: Path) -> np.ndarray:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"Failed to load image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def save_png(path: Path, rgb: np.ndarray) -> None:
    ensure_dir(path.parent)
    Image.fromarray(rgb.astype(np.uint8)).save(path)


def save_json(path: Path, payload: object) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
