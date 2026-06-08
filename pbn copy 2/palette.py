from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import PipelineConfig
from .superpixels import SuperpixelData
from .utils import rgb_to_hex


@dataclass
class PaletteData:
    lab: np.ndarray
    rgb: np.ndarray


# 30 fixed colors chosen for maximum perceptual separation:
#   - 12 bright hues  (HSV S=1, V=1) evenly spaced at 30° steps
#   - 12 dark hues    (HSV S=1, V=0.5) same hue steps
#   - 6 neutrals      (black, white, and 4 grays / skin tone)
_DEFAULT_PALETTE_RGB: np.ndarray = np.array(
    [
        # ── bright hues (H = 0, 30, 60 … 330 °, S=1, V=1) ─────────────────
        [255,   0,   0],   # red
        [255, 128,   0],   # orange
        [255, 255,   0],   # yellow
        [128, 255,   0],   # chartreuse
        [  0, 255,   0],   # green
        [  0, 255, 128],   # spring green
        [  0, 255, 255],   # cyan
        [  0, 128, 255],   # azure
        [  0,   0, 255],   # blue
        [128,   0, 255],   # violet
        [255,   0, 255],   # magenta
        [255,   0, 128],   # rose
        # ── dark hues (H = 0, 30, 60 … 330 °, S=1, V=0.5) ──────────────────
        [128,   0,   0],   # maroon
        [128,  64,   0],   # brown
        [128, 128,   0],   # olive
        [ 64, 128,   0],   # dark chartreuse
        [  0, 128,   0],   # dark green
        [  0, 128,  64],   # forest
        [  0, 128, 128],   # teal
        [  0,  64, 128],   # dark azure
        [  0,   0, 128],   # navy
        [ 64,   0, 128],   # dark violet
        [128,   0, 128],   # purple
        [128,   0,  64],   # dark rose
        # ── neutrals ────────────────────────────────────────────────────────
        [  0,   0,   0],   # black
        [ 64,  64,  64],   # dark gray
        [128, 128, 128],   # gray
        [192, 192, 192],   # light gray
        [255, 255, 255],   # white
        [210, 170, 125],   # skin / tan
    ],
    dtype=np.uint8,
)


def _rgb_rows_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert (N, 3) uint8 RGB → (N, 3) float32 OpenCV-LAB."""
    rgb_u8 = rgb.astype(np.uint8).reshape(1, -1, 3)
    lab = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2LAB).reshape(-1, 3)
    return lab.astype(np.float32)


def _lab_to_rgb_rows(lab: np.ndarray) -> np.ndarray:
    lab_u8 = np.clip(lab, 0, 255).astype(np.uint8).reshape(1, -1, 3)
    rgb = cv2.cvtColor(lab_u8, cv2.COLOR_LAB2RGB).reshape(-1, 3)
    return rgb.astype(np.uint8)


def build_palette_from_superpixels(sp_data: SuperpixelData, cfg: PipelineConfig) -> PaletteData:
    """Return the fixed 30-color palette converted to LAB space."""
    palette_rgb = _DEFAULT_PALETTE_RGB.copy()
    palette_lab = _rgb_rows_to_lab(palette_rgb)
    return PaletteData(lab=palette_lab, rgb=palette_rgb)


def assign_superpixels_to_palette(mean_lab: np.ndarray, palette_lab: np.ndarray) -> np.ndarray:
    d = ((mean_lab[:, None, :] - palette_lab[None, :, :]) ** 2).sum(axis=2)
    return np.argmin(d, axis=1).astype(np.int32)


def make_palette_records(palette_lab: np.ndarray, palette_rgb: np.ndarray) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for i, (lab, rgb) in enumerate(zip(palette_lab, palette_rgb), start=1):
        rgb_int = [int(v) for v in rgb]
        records.append(
            {
                "number": i,
                "rgb": rgb_int,
                "hex": rgb_to_hex(rgb_int),
                "lab": [float(round(v, 3)) for v in lab.tolist()],
            }
        )
    return records
