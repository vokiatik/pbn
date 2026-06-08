from __future__ import annotations

import cv2
import numpy as np
from skimage import color

from .pbn_config import IslandCleanupConfigV2


def _delta_e_rows(a_lab: np.ndarray, b_lab: np.ndarray) -> np.ndarray:
    return color.deltaE_ciede2000(a_lab[:, None, :], b_lab[None, :, :]).astype(np.float32)


def _component_masks_for_label(label_map: np.ndarray, label_id: int) -> tuple[int, np.ndarray, np.ndarray]:
    mask = (label_map == label_id).astype(np.uint8)
    n, cc, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    return n, cc, stats


def cleanup_color_islands(
    label_map: np.ndarray,
    palette_lab: np.ndarray,
    image_lab: np.ndarray,
    cfg: IslandCleanupConfigV2,
    protected_mask: np.ndarray,
    foreground_mask: np.ndarray,
    edge_strength: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    out = label_map.copy().astype(np.int32)
    h, w = out.shape
    total_px = h * w

    base_min_area = max(int(cfg.min_island_area_px), int(round(float(cfg.min_island_area_percent) * float(total_px))))
    merged_mask = np.zeros_like(out, dtype=np.uint8)
    edge_barrier = float(np.percentile(edge_strength, 83.0))

    fg_bool = foreground_mask > 0
    prot_bool = protected_mask > 0

    for _ in range(int(max(1, cfg.max_iterations))):
        changed = False
        labels_unique = np.unique(out)

        for color_id in labels_unique.tolist():
            n, cc, stats = _component_masks_for_label(out, int(color_id))
            for comp_id in range(1, n):
                area = int(stats[comp_id, cv2.CC_STAT_AREA])
                comp_mask = cc == comp_id
                if area <= 0:
                    continue

                prot_cov = float(np.mean(prot_bool[comp_mask]))
                fg_cov = float(np.mean(fg_bool[comp_mask]))
                edge_mean = float(np.mean(edge_strength[comp_mask]))

                local_min = float(base_min_area)
                if fg_cov > 0.5:
                    local_min *= float(cfg.foreground_area_multiplier)
                else:
                    local_min *= float(cfg.background_area_multiplier)
                if prot_cov > 0.06:
                    local_min *= float(cfg.protected_area_multiplier)

                if float(area) >= local_min:
                    continue
                if prot_cov > 0.18:
                    continue

                ring = cv2.dilate(comp_mask.astype(np.uint8), np.ones((3, 3), dtype=np.uint8), iterations=1).astype(bool)
                ring = np.logical_and(ring, np.logical_not(comp_mask))
                neigh_vals = out[ring]
                if neigh_vals.size == 0:
                    continue

                neigh_ids, neigh_counts = np.unique(neigh_vals, return_counts=True)
                if neigh_ids.size == 0:
                    continue
                dominant_idx = int(np.argmax(neigh_counts))
                dominant_label = int(neigh_ids[dominant_idx])
                dominant_ratio = float(neigh_counts[dominant_idx]) / max(1.0, float(neigh_counts.sum()))

                comp_lab = image_lab[comp_mask].mean(axis=0, dtype=np.float32)
                neigh_labs = palette_lab[neigh_ids.astype(np.int32)]
                de_all = _delta_e_rows(comp_lab[None, :].astype(np.float32), neigh_labs)[0]
                best_neigh_id = int(neigh_ids[int(np.argmin(de_all))])
                best_de = float(np.min(de_all))
                dominant_de = float(de_all[dominant_idx])

                low_contrast = best_de <= float(cfg.island_merge_delta_e)
                surrounded = (
                    dominant_ratio >= float(cfg.surrounded_boundary_ratio)
                    and dominant_de <= float(cfg.island_merge_delta_e + 6.0)
                )
                low_edge = edge_mean < edge_barrier

                if surrounded and low_edge:
                    target = dominant_label
                elif low_contrast and low_edge:
                    target = best_neigh_id
                else:
                    continue

                if target == int(color_id):
                    continue

                out[comp_mask] = int(target)
                merged_mask[comp_mask] = 255
                changed = True

        if not changed:
            break

    return out.astype(np.int32), merged_mask.astype(np.uint8)
