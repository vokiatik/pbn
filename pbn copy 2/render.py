from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy import ndimage

from .utils import rgb_to_hex


@dataclass
class FinalRegion:
    region_id: int
    color_label: int
    area: int
    centroid_xy: tuple[float, float]
    bbox_xywh: tuple[int, int, int, int]
    number_position_xy: tuple[int, int] | None
    number_clearance: float
    number_skipped: bool


def build_final_label_map(sp_label_map: np.ndarray, sp_color_labels: np.ndarray) -> np.ndarray:
    return sp_color_labels[sp_label_map].astype(np.int32)


def _majority3x3(label_map: np.ndarray) -> np.ndarray:
    def mode_fn(x: np.ndarray) -> int:
        values = x.astype(np.int32)
        return int(np.bincount(values).argmax())

    return ndimage.generic_filter(label_map, mode_fn, size=3).astype(np.int32)


def cleanup_label_map(label_map: np.ndarray, passes: int = 1) -> np.ndarray:
    out = label_map.copy()
    if passes <= 0:
        return out

    for _ in range(passes):
        out = _majority3x3(out)
    return out


def labels_to_preview(label_map: np.ndarray, palette_rgb: np.ndarray) -> np.ndarray:
    return palette_rgb[label_map].astype(np.uint8)


def _find_boundaries(label_map: np.ndarray, line_width: int) -> np.ndarray:
    edges = np.zeros_like(label_map, dtype=np.uint8)
    edges[:, 1:] |= (label_map[:, 1:] != label_map[:, :-1]).astype(np.uint8)
    edges[1:, :] |= (label_map[1:, :] != label_map[:-1, :]).astype(np.uint8)

    if line_width > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (line_width, line_width))
        edges = cv2.dilate(edges, k, iterations=1)
    return edges


def _best_number_point(mask: np.ndarray) -> tuple[int, int, float] | None:
    if not np.any(mask):
        return None
    dist = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    _, best, _, pt = cv2.minMaxLoc(dist)
    if best < 1.8:
        return None
    return int(pt[0]), int(pt[1]), float(best)


def _extract_regions(label_map: np.ndarray) -> list[FinalRegion]:
    regions: list[FinalRegion] = []
    next_id = 1

    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        num, cc, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for k in range(1, num):
            area = int(stats[k, cv2.CC_STAT_AREA])
            x = int(stats[k, cv2.CC_STAT_LEFT])
            y = int(stats[k, cv2.CC_STAT_TOP])
            w = int(stats[k, cv2.CC_STAT_WIDTH])
            h = int(stats[k, cv2.CC_STAT_HEIGHT])
            cx = float(cent[k, 0])
            cy = float(cent[k, 1])
            region_mask = cc == k
            best = _best_number_point(region_mask)
            pos = None if best is None else (best[0], best[1])
            clearance = 0.0 if best is None else float(best[2])
            regions.append(
                FinalRegion(
                    region_id=next_id,
                    color_label=int(color),
                    area=area,
                    centroid_xy=(cx, cy),
                    bbox_xywh=(x, y, w, h),
                    number_position_xy=pos,
                    number_clearance=clearance,
                    number_skipped=False,
                )
            )
            next_id += 1

    return regions


def render_lines_and_numbers(label_map: np.ndarray, line_width: int, min_number_area: int) -> tuple[np.ndarray, list[FinalRegion]]:
    h, w = label_map.shape
    canvas = np.full((h, w, 3), 255, dtype=np.uint8)

    boundaries = _find_boundaries(label_map, line_width)
    canvas[boundaries > 0] = (0, 0, 0)

    regions = _extract_regions(label_map)

    font = cv2.FONT_HERSHEY_SIMPLEX
    for region in regions:
        if region.area < min_number_area or region.number_position_xy is None:
            region.number_skipped = True
            continue

        text = str(region.color_label + 1)
        px, py = region.number_position_xy
        drawn = False
        for scale in (0.18, 0.16, 0.14, 0.12):
            (tw, th), baseline = cv2.getTextSize(text, font, scale, 1)
            # Fit check tuned to keep labels while still reducing border overlap.
            needed_clearance = 0.42 * float(max(tw + 2, th + baseline + 2))
            if region.number_clearance < needed_clearance:
                continue

            tx = int(px - tw / 2)
            ty = int(py + th / 2)
            cv2.putText(canvas, text, (tx, ty), font, scale, (0, 0, 0), 1, cv2.LINE_AA)
            drawn = True
            break

        if not drawn:
            region.number_skipped = True

    return canvas, regions


def render_palette_image(palette_rgb: np.ndarray, swatch_width: int = 260, swatch_height: int = 90) -> np.ndarray:
    rows = len(palette_rgb)
    width = swatch_width
    height = rows * swatch_height
    img = np.full((height, width, 3), 255, dtype=np.uint8)

    for i, rgb in enumerate(palette_rgb, start=1):
        y0 = (i - 1) * swatch_height
        y1 = y0 + swatch_height
        img[y0:y1, : int(width * 0.42)] = rgb

        text = f"{i:02d}  RGB {int(rgb[0])},{int(rgb[1])},{int(rgb[2])}  {rgb_to_hex(rgb)}"
        cv2.putText(img, text, (int(width * 0.45), y0 + int(swatch_height * 0.62)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (20, 20, 20), 1, cv2.LINE_AA)
        cv2.line(img, (0, y0), (width - 1, y0), (235, 235, 235), 1)

    return img


def extract_region_metadata(regions: list[FinalRegion], label_map: np.ndarray) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for r in regions:
        result.append(
            {
                "region_id": r.region_id,
                "color_number": int(r.color_label + 1),
                "area": int(r.area),
                "centroid": [float(round(r.centroid_xy[0], 3)), float(round(r.centroid_xy[1], 3))],
                "bbox": [int(v) for v in r.bbox_xywh],
                "number_skipped": bool(r.number_skipped),
                "number_position": list(r.number_position_xy) if r.number_position_xy is not None else None,
            }
        )
    return result
