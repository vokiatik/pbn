from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from skimage.segmentation import slic

from .pbn_config import SlicConfig


@dataclass
class SuperpixelResult:
    labels: np.ndarray
    n_labels: int
    area: np.ndarray
    mean_lab: np.ndarray
    mean_rgb: np.ndarray
    neighbors: dict[int, set[int]]


def _build_neighbors(labels: np.ndarray) -> dict[int, set[int]]:
    neighbors: dict[int, set[int]] = {}

    def connect(a: np.ndarray, b: np.ndarray) -> None:
        diff = a != b
        if not np.any(diff):
            return
        aa = a[diff].astype(np.int32)
        bb = b[diff].astype(np.int32)
        for left, right in zip(aa.tolist(), bb.tolist()):
            neighbors.setdefault(left, set()).add(right)
            neighbors.setdefault(right, set()).add(left)

    connect(labels[:, :-1], labels[:, 1:])
    connect(labels[:-1, :], labels[1:, :])
    return neighbors


def _run_slic(image_rgb: np.ndarray, cfg: SlicConfig, n_segments: int) -> np.ndarray:
    return slic(
        image_rgb,
        n_segments=max(64, int(n_segments)),
        compactness=cfg.compactness,
        sigma=cfg.sigma,
        start_label=0,
        convert2lab=True,
        enforce_connectivity=True,
        slic_zero=False,
    ).astype(np.int32)


def _adaptive_labels(
    image_rgb: np.ndarray,
    edge_strength: np.ndarray,
    protected_mask: np.ndarray | None,
    cfg: SlicConfig,
) -> np.ndarray:
    coarse = _run_slic(image_rgb, cfg, cfg.n_segments)
    coarse_count = int(coarse.max()) + 1

    fine_factor = 1.8 + 0.9 * float(cfg.edge_density_boost)
    if protected_mask is not None and np.any(protected_mask > 0):
        fine_factor += 0.35 * float(cfg.protected_region_boost)
    fine = _run_slic(image_rgb, cfg, int(round(cfg.n_segments * fine_factor)))

    edge_density = cv2.GaussianBlur(edge_strength.astype(np.float32), (0, 0), sigmaX=2.2, sigmaY=2.2)
    edge_density = edge_density - float(edge_density.min())
    edge_density = edge_density / max(float(edge_density.max()), 1e-6)
    thr = float(np.percentile(edge_density, float(np.clip(72.0 - 8.0 * cfg.edge_density_boost, 35.0, 80.0))))
    refine = edge_density >= thr

    if protected_mask is not None:
        protect = (protected_mask > 0).astype(np.uint8)
        if cfg.protected_mask_dilate_px > 0:
            k = 2 * cfg.protected_mask_dilate_px + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            protect = cv2.dilate(protect, kernel, iterations=1)
        refine = np.logical_or(refine, protect > 0)

    mixed = coarse.copy()
    mixed[refine] = fine[refine] + coarse_count
    _, dense = np.unique(mixed, return_inverse=True)
    return dense.reshape(mixed.shape).astype(np.int32)


def compute_superpixels(
    image_rgb: np.ndarray,
    image_lab: np.ndarray,
    cfg: SlicConfig,
    edge_strength: np.ndarray | None = None,
    protected_mask: np.ndarray | None = None,
) -> SuperpixelResult:
    if cfg.adaptive and edge_strength is not None:
        labels = _adaptive_labels(
            image_rgb,
            edge_strength=edge_strength,
            protected_mask=protected_mask,
            cfg=cfg,
        )
    else:
        labels = _run_slic(image_rgb, cfg, cfg.n_segments)

    flat = labels.ravel()
    n_labels = int(labels.max()) + 1
    area = np.bincount(flat, minlength=n_labels).astype(np.int32)

    mean_lab = np.zeros((n_labels, 3), dtype=np.float32)
    mean_rgb = np.zeros((n_labels, 3), dtype=np.float32)

    for c in range(3):
        mean_lab[:, c] = np.bincount(flat, weights=image_lab[:, :, c].ravel(), minlength=n_labels) / np.maximum(area, 1)
        mean_rgb[:, c] = np.bincount(flat, weights=image_rgb[:, :, c].ravel(), minlength=n_labels) / np.maximum(area, 1)

    return SuperpixelResult(
        labels=labels,
        n_labels=n_labels,
        area=area,
        mean_lab=mean_lab,
        mean_rgb=mean_rgb,
        neighbors=_build_neighbors(labels),
    )
