from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class RegionNumber:
    region_id: int
    color_label: int
    area: int
    centroid_xy: tuple[float, float]
    number_position_xy: tuple[int, int] | None
    number_skipped: bool
    max_inscribed_circle_radius: float
    uses_external_label: bool = False
    leader_line_start_xy: tuple[int, int] | None = None
    leader_line_end_xy: tuple[int, int] | None = None


def _best_point(mask: np.ndarray) -> tuple[int, int, float] | None:
    if not np.any(mask):
        return None
    dist = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    _, best, _, pt = cv2.minMaxLoc(dist)
    if best < 1.6:
        return None
    return int(pt[0]), int(pt[1]), float(best)


def _external_label_position(
    shape: tuple[int, int],
    centroid_xy: tuple[float, float],
    anchor_xy: tuple[int, int],
    region_mask: np.ndarray,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    h, w = shape
    cx, cy = centroid_xy
    ax, ay = anchor_xy

    left_count = int(np.sum(region_mask[:, : max(1, int(cx))]))
    right_count = int(np.sum(region_mask[:, int(cx) :]))
    sign = -1 if left_count >= right_count else 1

    lx = int(np.clip(ax + sign * 20, 8, w - 8))
    ly = int(np.clip(ay - 8, 8, h - 8))
    elbow = (int(np.clip(ax + sign * 10, 0, w - 1)), ay)
    return (lx, ly), (ax, ay), elbow


def place_region_numbers(
    label_map: np.ndarray,
    min_number_area_px: int,
    min_number_radius_px: float = 1.6,
    allow_external_labels: bool = True,
    max_external_labels_percent: float = 3.0,
    protected_mask: np.ndarray | None = None,
) -> list[RegionNumber]:
    regions: list[RegionNumber] = []
    external_candidates: list[tuple[int, float, bool, np.ndarray, tuple[int, int], tuple[float, float]]] = []
    rid = 1

    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        n, cc, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            region_mask = cc == i
            best = _best_point(region_mask)
            pos = None if best is None else (best[0], best[1])
            max_radius = 0.0 if best is None else float(best[2])
            internal_ok = area >= min_number_area_px and pos is not None and max_radius >= float(min_number_radius_px)
            skip = not internal_ok

            centroid_xy = (float(centroids[i, 0]), float(centroids[i, 1]))
            if not internal_ok:
                if pos is None:
                    pos = (int(round(centroid_xy[0])), int(round(centroid_xy[1])))
                protected_cov = 0.0
                if protected_mask is not None and np.any(region_mask):
                    protected_cov = float(np.mean((protected_mask > 0)[region_mask]))
                external_candidates.append((rid, protected_cov, bool(protected_cov >= 0.12), region_mask, pos, centroid_xy))

            regions.append(
                RegionNumber(
                    region_id=rid,
                    color_label=int(color),
                    area=area,
                    centroid_xy=centroid_xy,
                    number_position_xy=pos,
                    number_skipped=skip,
                    max_inscribed_circle_radius=max_radius,
                )
            )
            rid += 1

    if allow_external_labels and external_candidates:
        total = max(1, len(regions))
        soft_external_target = int(np.floor((float(max_external_labels_percent) / 100.0) * float(total)))
        soft_external_target = max(1, soft_external_target)
        ranked = sorted(external_candidates, key=lambda item: (-item[1], -regions[item[0] - 1].area))
        prioritized = ranked[:soft_external_target] + ranked[soft_external_target:]
        for region_id, _, _is_protected, region_mask, anchor_xy, centroid_xy in prioritized:
            region = regions[region_id - 1]
            label_xy, start_xy, elbow_xy = _external_label_position(label_map.shape, centroid_xy, anchor_xy, region_mask)
            region.number_position_xy = label_xy
            region.number_skipped = False
            region.uses_external_label = True
            region.leader_line_start_xy = start_xy
            region.leader_line_end_xy = elbow_xy

    return regions
