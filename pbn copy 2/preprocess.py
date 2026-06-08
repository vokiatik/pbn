from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import PipelineConfig
from .utils import resize_longest_side


@dataclass
class PreprocessResult:
    rgb: np.ndarray
    lab: np.ndarray
    edge_source_rgb: np.ndarray


def _lift_shadows_l_channel(lab_u8: np.ndarray) -> np.ndarray:
    out = lab_u8.copy()
    l = out[:, :, 0].astype(np.float32)
    p90 = float(np.percentile(l, 90.0))
    gamma = 0.85 if p90 < 190 else 0.92
    l_norm = np.clip(l / 255.0, 0.0, 1.0)
    lifted = np.power(l_norm, gamma)
    out[:, :, 0] = np.clip(lifted * 255.0, 0, 255).astype(np.uint8)
    return out


def _edge_preserving_denoise(rgb: np.ndarray, detail_level: float) -> np.ndarray:
    d = 9
    sigma_color = float(28.0 - 14.0 * detail_level)
    sigma_space = float(12.0 - 5.0 * detail_level)
    den = cv2.bilateralFilter(rgb, d=d, sigmaColor=sigma_color, sigmaSpace=sigma_space)

    ximgproc = getattr(cv2, "ximgproc", None)
    if ximgproc is not None and hasattr(ximgproc, "guidedFilter"):
        try:
            den = ximgproc.guidedFilter(guide=rgb, src=den, radius=6, eps=1e-2)
        except Exception:
            pass

    if ximgproc is not None and hasattr(ximgproc, "anisotropicDiffusion"):
        try:
            den = ximgproc.anisotropicDiffusion(den, alpha=0.15, K=20, niters=4)
            den = np.clip(den, 0, 255).astype(np.uint8)
        except Exception:
            pass

    return den


def preprocess_image(image_rgb: np.ndarray, config: PipelineConfig) -> PreprocessResult:
    h, w = image_rgb.shape[:2]
    new_w, new_h = resize_longest_side(w, h, config.size)
    resized = cv2.resize(image_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)

    edge_source = cv2.bilateralFilter(
        resized,
        d=7,
        sigmaColor=float(14.0 - 5.0 * config.detail_level),
        sigmaSpace=float(7.0 - 2.0 * config.detail_level),
    )

    lab = cv2.cvtColor(resized, cv2.COLOR_RGB2LAB)
    lab = _lift_shadows_l_channel(lab)
    lifted_rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

    denoised = _edge_preserving_denoise(lifted_rgb, detail_level=config.detail_level)
    den_lab = cv2.cvtColor(denoised, cv2.COLOR_RGB2LAB)
    return PreprocessResult(rgb=denoised, lab=den_lab, edge_source_rgb=edge_source)
