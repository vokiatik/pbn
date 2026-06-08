from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .config import PipelineConfig
from .palette import PaletteData
from .region_graph import build_region_graph
from .superpixels import SuperpixelData
from .utils import normalize01


def _face_importance(gray: np.ndarray) -> np.ndarray:
    imp = np.zeros_like(gray, dtype=np.float32)
    try:
        cv2_data = getattr(cv2, "data", None)
        if cv2_data is None or not hasattr(cv2_data, "haarcascades"):
            return imp
        cascade_path = cv2_data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return imp
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
        for x, y, w, h in faces:
            cv2.ellipse(imp, (x + w // 2, y + h // 2), (w // 2, h // 2), 0, 0, 360, 1.0, -1)
    except Exception:
        return imp
    return imp


def _central_bias(h: int, w: int) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx = (w - 1) * 0.5
    cy = (h - 1) * 0.5
    sx = max(1.0, w * 0.36)
    sy = max(1.0, h * 0.36)
    g = np.exp(-(((xx - cx) ** 2) / (2 * sx * sx) + ((yy - cy) ** 2) / (2 * sy * sy)))
    return normalize01(g)


def build_importance_map(rgb: np.ndarray, edge_strength: np.ndarray, mask_path: Path | None) -> np.ndarray:
    h, w = rgb.shape[:2]
    if mask_path is not None and mask_path.exists():
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is not None:
            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)
            return normalize01(mask)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    face = _face_importance(gray)
    edge_density = cv2.GaussianBlur(edge_strength, (0, 0), sigmaX=7.0, sigmaY=7.0)
    edge_density = normalize01(edge_density)
    center = _central_bias(h, w)

    imp = normalize01(0.45 * face + 0.35 * edge_density + 0.20 * center)
    return imp.astype(np.float32)


def _sp_mean_importance(sp_labels: np.ndarray, importance_map: np.ndarray, n_sp: int) -> np.ndarray:
    flat_sp = sp_labels.ravel()
    sums = np.bincount(flat_sp, weights=importance_map.ravel(), minlength=n_sp)
    cnts = np.bincount(flat_sp, minlength=n_sp)
    return (sums / np.maximum(cnts, 1)).astype(np.float32)


def safe_merge_tiny_regions(
    sp_data: SuperpixelData,
    palette: PaletteData,
    initial_sp_color_labels: np.ndarray,
    edge_strength: np.ndarray,
    importance_map: np.ndarray,
    config: PipelineConfig,
) -> np.ndarray:
    sp_color = initial_sp_color_labels.copy().astype(np.int32)
    base_min_area = config.resolve_default_min_region_area(sp_data.labels.shape[1], sp_data.labels.shape[0])
    detail_level = float(np.clip(config.detail_level, 0.0, 1.0))
    strong_edge_barrier = float(np.percentile(edge_strength, 68.0 + 14.0 * detail_level))

    sp_imp = _sp_mean_importance(sp_data.labels, importance_map, sp_data.count)

    for _ in range(config.merge_iterations):
        rg = build_region_graph(sp_data, palette, sp_color)
        if not rg.regions:
            break

        changed = False
        small_regions = sorted(rg.regions.values(), key=lambda r: r.area)

        for region in small_regions:
            region_imp = float(np.mean(sp_imp[np.array(region.superpixels, dtype=np.int32)]))
            local_min_area = int(
                round(base_min_area * (1.34 - 0.72 * region_imp) * (1.18 - 0.62 * detail_level))
            )
            local_min_area = max(8, local_min_area)

            if config.preserve_detail_regions and region_imp > 0.62:
                local_min_area = max(6, int(round(local_min_area * (0.55 - 0.25 * detail_level))))

            if region.area >= local_min_area:
                continue

            is_extremely_tiny = region.area <= max(6, int(0.2 * local_min_area))
            if config.preserve_detail_regions and region_imp > 0.72 and not is_extremely_tiny:
                continue

            local_edge_thr = float(
                np.clip(
                    config.edge_threshold * (1.18 - 0.62 * region_imp) * (1.06 - 0.52 * detail_level),
                    0.03,
                    0.95,
                )
            )
            local_lab_thr = float(
                np.clip(
                    config.lab_merge_threshold * (1.15 - 0.36 * region_imp) * (1.10 - 0.44 * detail_level),
                    6.0,
                    80.0,
                )
            )
            min_shared_ratio = float(np.clip(0.024 + 0.042 * detail_level - 0.010 * region_imp, 0.016, 0.11))

            border_items: list[tuple[int, int, int, float, float]] = []
            for key, b in rg.borders.items():
                if region.region_id == key[0]:
                    border_items.append((key[1], b.shared_border, region.color_label, b.edge_mean, b.lab_distance))
                elif region.region_id == key[1]:
                    border_items.append((key[0], b.shared_border, region.color_label, b.edge_mean, b.lab_distance))

            if not border_items:
                continue

            perimeter = float(sum(item[1] for item in border_items))
            best_target = None
            best_score = float("inf")

            for neighbor_id, shared, current_color, edge_mean, lab_dist in border_items:
                neigh = rg.regions[neighbor_id]
                shared_ratio = float(shared) / max(perimeter, 1.0)
                if shared_ratio < min_shared_ratio and not is_extremely_tiny:
                    continue

                if edge_mean >= strong_edge_barrier and region.area > 4:
                    continue

                if (lab_dist > local_lab_thr or edge_mean > local_edge_thr) and not is_extremely_tiny:
                    continue

                if config.preserve_detail_regions and region_imp > 0.66 and lab_dist > (0.8 * local_lab_thr):
                    continue

                palette_penalty = 0.4 if neigh.color_label != current_color else 0.0
                score = (
                    float(lab_dist) * 1.0
                    + float(edge_mean) * 2.5
                    - float(shared_ratio) * 1.5
                    + palette_penalty
                )
                if score < best_score:
                    best_score = score
                    best_target = neigh

            if best_target is None:
                continue

            sp_idx = np.array(region.superpixels, dtype=np.int32)
            sp_color[sp_idx] = int(best_target.color_label)
            changed = True

        if not changed:
            break

    return sp_color
