from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class RegionContour:
    region_id: int
    color_label: int
    area: int
    contour: np.ndarray


def extract_region_contours(label_map: np.ndarray, tolerance_px: float) -> list[RegionContour]:
    return extract_region_contours_adaptive(
        label_map=label_map,
        tolerance_px=tolerance_px,
        edge_strength=None,
        importance_map=None,
        protected_mask=None,
    )


def extract_region_contours_adaptive(
    label_map: np.ndarray,
    tolerance_px: float,
    edge_strength: np.ndarray | None,
    importance_map: np.ndarray | None,
    protected_mask: np.ndarray | None,
) -> list[RegionContour]:
    contours_out: list[RegionContour] = []
    rid = 1

    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        n, cc, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            component_mask = (cc == i).astype(np.uint8)
            found, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if not found:
                continue
            largest = max(found, key=cv2.contourArea)

            local_edge = 0.0
            if edge_strength is not None and np.any(component_mask > 0):
                local_edge = float(edge_strength[component_mask > 0].mean())

            local_importance = 0.0
            if importance_map is not None and np.any(component_mask > 0):
                local_importance = float(importance_map[component_mask > 0].mean())

            protected_score = 0.0
            if protected_mask is not None and np.any(component_mask > 0):
                protected_score = float((protected_mask[component_mask > 0] > 0).mean())

            scale = 1.18 - 0.58 * local_importance - 0.42 * local_edge
            if protected_score > 0.2:
                scale *= 0.55
            epsilon = max(0.2, float(tolerance_px) * float(np.clip(scale, 0.2, 1.45)))
            approx = cv2.approxPolyDP(largest, epsilon=epsilon, closed=True)
            contours_out.append(
                RegionContour(
                    region_id=rid,
                    color_label=int(color),
                    area=area,
                    contour=approx[:, 0, :].astype(np.int32),
                )
            )
            rid += 1

    return contours_out
