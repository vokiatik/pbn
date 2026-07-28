from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, path)


def save_label_map_png(label_map: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = label_map.astype(np.uint64)
    rgb = np.zeros((*labels.shape, 3), dtype=np.uint8)
    rgb[..., 0] = ((labels * 37) % 255).astype(np.uint8)
    rgb[..., 1] = ((labels * 91) % 255).astype(np.uint8)
    rgb[..., 2] = ((labels * 151) % 255).astype(np.uint8)
    Image.fromarray(rgb, mode="RGB").save(path)


def save_rgb(path: Path, rgb: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB").save(path)

