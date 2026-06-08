from __future__ import annotations

import cv2
import numpy as np

from .utils import normalize01


def build_edge_strength_map(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    canny_fine = cv2.Canny(gray, threshold1=45, threshold2=105, L2gradient=True).astype(np.float32) / 255.0
    canny_coarse = cv2.Canny(gray, threshold1=75, threshold2=165, L2gradient=True).astype(np.float32) / 255.0

    gx3 = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy3 = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    sobel3 = normalize01(np.sqrt(gx3 * gx3 + gy3 * gy3))

    gx5 = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=5)
    gy5 = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=5)
    sobel5 = normalize01(np.sqrt(gx5 * gx5 + gy5 * gy5))

    edge = normalize01(0.32 * sobel3 + 0.28 * sobel5 + 0.20 * canny_fine + 0.20 * canny_coarse)
    return edge.astype(np.float32)
