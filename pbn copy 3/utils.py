from __future__ import annotations

import numpy as np


def rgb_to_hex(rgb: np.ndarray | tuple[int, int, int] | list[int]) -> str:
    r, g, b = [int(x) for x in rgb]
    return f"#{r:02X}{g:02X}{b:02X}"


def normalize01(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    lo = float(arr.min())
    hi = float(arr.max())
    if hi - lo < 1e-9:
        return np.zeros_like(arr, dtype=np.float32)
    return (arr - lo) / (hi - lo)


def resize_longest_side(width: int, height: int, target_longest: int) -> tuple[int, int]:
    longest = max(width, height)
    if longest == target_longest:
        return width, height
    scale = target_longest / float(longest)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))
