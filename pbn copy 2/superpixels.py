from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage.segmentation import felzenszwalb, slic

from .config import PipelineConfig


@dataclass
class BoundaryStats:
    length: int
    edge_mean: float


@dataclass
class SuperpixelData:
    labels: np.ndarray
    count: int
    area: np.ndarray
    mean_lab: np.ndarray
    mean_rgb: np.ndarray
    mean_importance: np.ndarray
    neighbors: dict[int, dict[int, BoundaryStats]]


def _target_superpixel_count(width: int, height: int, cfg: PipelineConfig) -> int:
    area = width * height
    detail_scale = 1.00 + 2.10 * float(np.clip(cfg.detail_level, 0.0, 1.0))
    by_area = int(round((area / float(cfg.superpixel_area_px)) * detail_scale))
    return int(np.clip(by_area, cfg.superpixels_min, cfg.superpixels_max))


def _aggregate_boundaries(sp_labels: np.ndarray, edge: np.ndarray) -> dict[int, dict[int, BoundaryStats]]:
    neighbors: dict[int, dict[int, BoundaryStats]] = {}

    def add_pairs(a: np.ndarray, b: np.ndarray, e: np.ndarray) -> None:
        m = a != b
        if not np.any(m):
            return
        left = np.minimum(a[m], b[m]).astype(np.int32)
        right = np.maximum(a[m], b[m]).astype(np.int32)
        pairs = np.stack([left, right], axis=1)
        unique_pairs, inv = np.unique(pairs, axis=0, return_inverse=True)
        counts = np.bincount(inv)
        edge_sum = np.bincount(inv, weights=e[m].astype(np.float64))
        for idx, pair in enumerate(unique_pairs):
            i = int(pair[0])
            j = int(pair[1])
            stat = BoundaryStats(length=int(counts[idx]), edge_mean=float(edge_sum[idx] / max(1, counts[idx])))
            neighbors.setdefault(i, {})[j] = stat
            neighbors.setdefault(j, {})[i] = stat

    add_pairs(sp_labels[:, :-1], sp_labels[:, 1:], 0.5 * (edge[:, :-1] + edge[:, 1:]))
    add_pairs(sp_labels[:-1, :], sp_labels[1:, :], 0.5 * (edge[:-1, :] + edge[1:, :]))
    return neighbors


def compute_superpixels(rgb: np.ndarray, lab: np.ndarray, edge_strength: np.ndarray, cfg: PipelineConfig) -> SuperpixelData:
    h, w = rgb.shape[:2]
    n_segments = _target_superpixel_count(w, h, cfg)
    detail_level = float(np.clip(cfg.detail_level, 0.0, 1.0))

    if cfg.superpixel_shape == "square":
        compactness = float(12.0 - 4.0 * detail_level)
        sigma = float(max(0.3, 0.9 - 0.30 * detail_level))
        slic_zero = False
        sp_labels = slic(
            rgb,
            n_segments=n_segments,
            compactness=compactness,
            sigma=sigma,
            slic_zero=slic_zero,
            start_label=0,
            convert2lab=False,
            enforce_connectivity=True,
        ).astype(np.int32)
    else:
        # Irregular, edge-following regions for adaptive modes.
        rgb01 = rgb.astype(np.float32) / 255.0
        if cfg.superpixel_shape == "very-adaptive":
            sigma = float(max(0.0, 0.45 - 0.28 * detail_level))
            min_size = int(max(10, round(cfg.superpixel_area_px * 0.30)))
            scale = float(max(10.0, 55.0 - 30.0 * detail_level))
        else:
            sigma = float(max(0.1, 0.65 - 0.30 * detail_level))
            min_size = int(max(16, round(cfg.superpixel_area_px * 0.48)))
            scale = float(max(20.0, 95.0 - 40.0 * detail_level))

        sp_labels = felzenszwalb(
            rgb01,
            scale=scale,
            sigma=sigma,
            min_size=min_size,
            channel_axis=-1,
        ).astype(np.int32)

        # Densify labels to 0..N-1 for bincount-based aggregation.
        _, sp_labels = np.unique(sp_labels, return_inverse=True)
        sp_labels = sp_labels.reshape(h, w).astype(np.int32)

    n_sp = int(sp_labels.max() + 1)
    flat = sp_labels.ravel()

    area = np.bincount(flat, minlength=n_sp).astype(np.int32)

    mean_lab = np.zeros((n_sp, 3), dtype=np.float32)
    mean_rgb = np.zeros((n_sp, 3), dtype=np.float32)
    mean_importance = np.zeros((n_sp,), dtype=np.float32)

    for c in range(3):
        mean_lab[:, c] = np.bincount(flat, weights=lab[:, :, c].ravel(), minlength=n_sp) / np.maximum(area, 1)
        mean_rgb[:, c] = np.bincount(flat, weights=rgb[:, :, c].ravel(), minlength=n_sp) / np.maximum(area, 1)

    mean_importance[:] = np.bincount(flat, weights=edge_strength.ravel(), minlength=n_sp) / np.maximum(area, 1)

    neighbors = _aggregate_boundaries(sp_labels, edge_strength)
    return SuperpixelData(
        labels=sp_labels,
        count=n_sp,
        area=area,
        mean_lab=mean_lab,
        mean_rgb=mean_rgb,
        mean_importance=mean_importance,
        neighbors=neighbors,
    )
