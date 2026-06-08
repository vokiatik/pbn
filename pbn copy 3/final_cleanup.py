from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class FinalSimplifyConfig:
    print_dpi: int
    min_paintable_diameter_mm: float = 5.0
    min_region_area_mm2: float = 20.0
    min_inscribed_circle_radius_mm: float = 2.5
    min_region_width_mm: float = 4.0
    min_region_height_mm: float = 4.0
    max_regions_per_cm2: float = 6.0
    max_border_length_per_cm2: float = 45.0
    local_density_window_mm: float = 15.0
    hole_fill_area_mm2: float = 10.0
    sliver_min_width_mm: float = 2.0
    branch_min_width_mm: float = 2.0
    max_iterations: int = 28


@dataclass
class FinalSimplifyResult:
    label_map: np.ndarray
    unpaintable_regions_mask: np.ndarray
    dense_line_areas_mask: np.ndarray
    region_count_before: int
    region_count_after: int
    average_region_area_before: float
    average_region_area_after: float
    smallest_region_report: list[dict[str, float | int]]


def _mm_to_px(mm: float, dpi: int) -> float:
    return (float(mm) / 25.4) * float(dpi)


def _mm2_to_px2(mm2: float, dpi: int) -> float:
    px_per_mm = float(dpi) / 25.4
    return float(mm2) * px_per_mm * px_per_mm


def _label_boundary_mask(label_map: np.ndarray) -> np.ndarray:
    boundary = np.zeros_like(label_map, dtype=np.uint8)
    boundary[:, 1:] = np.maximum(boundary[:, 1:], (label_map[:, 1:] != label_map[:, :-1]).astype(np.uint8) * 255)
    boundary[1:, :] = np.maximum(boundary[1:, :], (label_map[1:, :] != label_map[:-1, :]).astype(np.uint8) * 255)
    return boundary


def _region_summary(label_map: np.ndarray) -> tuple[int, float]:
    areas: list[int] = []
    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            areas.append(int(stats[i, cv2.CC_STAT_AREA]))
    if not areas:
        return 0, 0.0
    return len(areas), float(np.mean(np.asarray(areas, dtype=np.float32)))


def _component_maps(label_map: np.ndarray) -> tuple[np.ndarray, dict[int, dict[str, float | int]]]:
    h, w = label_map.shape
    comp_map = np.zeros((h, w), dtype=np.int32)
    info: dict[int, dict[str, float | int]] = {}
    next_id = 1

    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        n, cc, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            cid = next_id
            next_id += 1
            comp_mask = cc == i
            comp_map[comp_mask] = cid
            area = int(stats[i, cv2.CC_STAT_AREA])
            bw = int(stats[i, cv2.CC_STAT_WIDTH])
            bh = int(stats[i, cv2.CC_STAT_HEIGHT])
            dist = cv2.distanceTransform(comp_mask.astype(np.uint8), cv2.DIST_L2, 5)
            radius = float(dist.max()) if area > 0 else 0.0
            info[cid] = {
                "component_id": int(cid),
                "color": int(color),
                "area": int(area),
                "bbox_width": int(bw),
                "bbox_height": int(bh),
                "radius": float(radius),
            }

    return comp_map, info


def _component_neighbors_and_boundaries(
    comp_map: np.ndarray,
    edge_strength: np.ndarray,
) -> tuple[dict[int, set[int]], dict[tuple[int, int], int], dict[tuple[int, int], float], dict[int, dict[int, int]]]:
    neighbors: dict[int, set[int]] = {}
    shared: dict[tuple[int, int], int] = {}
    edge_sum: dict[tuple[int, int], float] = {}
    ring_votes: dict[int, dict[int, int]] = {}

    def collect(a: np.ndarray, b: np.ndarray, e: np.ndarray) -> None:
        diff = a != b
        if not np.any(diff):
            return
        aa = a[diff].astype(np.int32)
        bb = b[diff].astype(np.int32)
        ee = e[diff].astype(np.float32)
        for left, right, edge_v in zip(aa.tolist(), bb.tolist(), ee.tolist()):
            if left <= 0 or right <= 0 or left == right:
                continue
            neighbors.setdefault(left, set()).add(right)
            neighbors.setdefault(right, set()).add(left)
            key = (left, right) if left < right else (right, left)
            shared[key] = shared.get(key, 0) + 1
            edge_sum[key] = edge_sum.get(key, 0.0) + float(edge_v)
            ring_votes.setdefault(left, {})[right] = ring_votes.setdefault(left, {}).get(right, 0) + 1
            ring_votes.setdefault(right, {})[left] = ring_votes.setdefault(right, {}).get(left, 0) + 1

    collect(comp_map[:, :-1], comp_map[:, 1:], 0.5 * (edge_strength[:, :-1] + edge_strength[:, 1:]))
    collect(comp_map[:-1, :], comp_map[1:, :], 0.5 * (edge_strength[:-1, :] + edge_strength[1:, :]))

    edge_mean: dict[tuple[int, int], float] = {}
    for key, total in edge_sum.items():
        edge_mean[key] = float(total / max(1, shared.get(key, 1)))

    return neighbors, shared, edge_mean, ring_votes


def _component_mean_lab(comp_map: np.ndarray, image_lab: np.ndarray) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    flat_comp = comp_map.ravel()
    flat_lab = image_lab.reshape(-1, 3)
    for cid in np.unique(flat_comp).tolist():
        if cid <= 0:
            continue
        mask = flat_comp == cid
        if np.any(mask):
            out[int(cid)] = flat_lab[mask].mean(axis=0).astype(np.float32)
    return out


def _dense_line_mask(label_map: np.ndarray, cfg: FinalSimplifyConfig) -> np.ndarray:
    boundary = _label_boundary_mask(label_map).astype(np.float32) / 255.0
    window_px = max(3, int(round(_mm_to_px(cfg.local_density_window_mm, cfg.print_dpi))))
    if window_px % 2 == 0:
        window_px += 1

    border_density_local = cv2.boxFilter(boundary, ddepth=-1, ksize=(window_px, window_px), normalize=False)
    px_per_cm = float(cfg.print_dpi) / 2.54
    px_per_cm2 = px_per_cm * px_per_cm
    border_density_cm2 = border_density_local * (px_per_cm2 / float(window_px * window_px))

    centers = np.zeros_like(boundary, dtype=np.float32)
    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        n, _, _, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            cx = int(np.clip(round(float(centroids[i, 0])), 0, label_map.shape[1] - 1))
            cy = int(np.clip(round(float(centroids[i, 1])), 0, label_map.shape[0] - 1))
            centers[cy, cx] += 1.0
    region_density_local = cv2.boxFilter(centers, ddepth=-1, ksize=(window_px, window_px), normalize=False)
    region_density_cm2 = region_density_local * (px_per_cm2 / float(window_px * window_px))

    dense = np.logical_or(
        region_density_cm2 > float(cfg.max_regions_per_cm2),
        border_density_cm2 > float(cfg.max_border_length_per_cm2),
    )

    dense_u8 = (dense.astype(np.uint8) * 255)
    dense_u8 = cv2.morphologyEx(dense_u8, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return dense_u8


def _micro_contour_cleanup(
    label_map: np.ndarray,
    protected_mask: np.ndarray,
    cfg: FinalSimplifyConfig,
) -> np.ndarray:
    out = label_map.copy().astype(np.int32)
    protect = protected_mask > 0

    hole_fill_area_px = int(round(_mm2_to_px2(cfg.hole_fill_area_mm2, cfg.print_dpi)))
    sliver_min_width_px = max(1, int(round(_mm_to_px(cfg.sliver_min_width_mm, cfg.print_dpi))))
    branch_min_width_px = max(1, int(round(_mm_to_px(cfg.branch_min_width_mm, cfg.print_dpi))))

    for _ in range(2):
        # Fill tiny holes by relabeling small enclosed components to dominant local neighbor.
        comp_map, info = _component_maps(out)
        neighbors, _, _, ring_votes = _component_neighbors_and_boundaries(comp_map, np.zeros_like(out, dtype=np.float32))
        for cid, cinfo in info.items():
            area = int(cinfo["area"])
            bw = int(cinfo["bbox_width"])
            bh = int(cinfo["bbox_height"])
            if area > hole_fill_area_px and bw >= sliver_min_width_px and bh >= sliver_min_width_px:
                continue
            mask = comp_map == int(cid)
            if np.any(protect[mask]):
                continue
            votes = ring_votes.get(int(cid), {})
            if not votes:
                continue
            target_cid = max(votes.items(), key=lambda kv: kv[1])[0]
            target_color = int(info.get(target_cid, {}).get("color", cinfo["color"]))
            out[mask] = target_color

        # Remove one/two-pixel corridors outside protected edges.
        smooth = cv2.medianBlur(out.astype(np.uint8), 3).astype(np.int32)
        out = np.where(protect, out, smooth)

        # Remove narrow branch-like bits by erosion-recover approach per color.
        for color in np.unique(out):
            mask = (out == color).astype(np.uint8)
            eroded = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, branch_min_width_px), max(3, branch_min_width_px))), iterations=1)
            recover = cv2.dilate(eroded, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, branch_min_width_px), max(3, branch_min_width_px))), iterations=1)
            drop = np.logical_and(mask > 0, recover == 0)
            drop = np.logical_and(drop, np.logical_not(protect))
            if np.any(drop):
                out[drop] = 255

        # Resolve temporary unlabeled pixels by local majority voting.
        unlabeled = out == 255
        if np.any(unlabeled):
            base = out.copy()
            base[unlabeled] = 0
            for _ in range(2):
                neighborhood = cv2.blur(base.astype(np.float32), (3, 3))
                fill = neighborhood.astype(np.int32)
                base[unlabeled] = fill[unlabeled]
            out[unlabeled] = base[unlabeled]

    return out.astype(np.int32)


def simplify_final_regions(
    label_map: np.ndarray,
    palette_lab: np.ndarray,
    image_lab: np.ndarray,
    edge_strength: np.ndarray,
    protected_mask: np.ndarray,
    cfg: FinalSimplifyConfig,
) -> FinalSimplifyResult:
    current = label_map.copy().astype(np.int32)
    before_count, before_avg = _region_summary(current)

    min_diameter_px = float(_mm_to_px(cfg.min_paintable_diameter_mm, cfg.print_dpi))
    min_area_px = max(
        int(round(_mm2_to_px2(cfg.min_region_area_mm2, cfg.print_dpi))),
        int(round(np.pi * ((0.5 * min_diameter_px) ** 2))),
    )
    min_radius_px = float(_mm_to_px(cfg.min_inscribed_circle_radius_mm, cfg.print_dpi))
    min_width_px = int(round(_mm_to_px(cfg.min_region_width_mm, cfg.print_dpi)))
    min_height_px = int(round(_mm_to_px(cfg.min_region_height_mm, cfg.print_dpi)))

    edge_barrier = float(np.percentile(edge_strength, 84.0))
    dense_mask = _dense_line_mask(current, cfg)

    unpaintable_mask = np.zeros_like(current, dtype=np.uint8)

    for _ in range(max(1, int(cfg.max_iterations))):
        changed = False
        comp_map, info = _component_maps(current)
        if not info:
            break

        comp_lab = _component_mean_lab(comp_map, image_lab)
        neighbors, shared, edge_mean, ring_votes = _component_neighbors_and_boundaries(comp_map, edge_strength)

        invalid_components: list[int] = []
        for cid, cinfo in info.items():
            cid_i = int(cid)
            mask = comp_map == cid_i
            area = int(cinfo["area"])
            bw = int(cinfo["bbox_width"])
            bh = int(cinfo["bbox_height"])
            radius = float(cinfo["radius"])
            dense_cov = float(np.mean((dense_mask > 0)[mask])) if np.any(mask) else 0.0
            protected_cov = float(np.mean((protected_mask > 0)[mask])) if np.any(mask) else 0.0

            not_paintable = (
                area < min_area_px
                or bw < min_width_px
                or bh < min_height_px
                or radius < min_radius_px
                or dense_cov > 0.35
            )

            if not_paintable and protected_cov < 0.35:
                invalid_components.append(cid_i)
                unpaintable_mask[mask] = 255

        if not invalid_components:
            break

        for cid in sorted(invalid_components, key=lambda x: int(info[x]["area"])):
            if cid not in info:
                continue
            mask = comp_map == cid
            neigh_ids = [nid for nid in neighbors.get(cid, set()) if nid in info]
            if not neigh_ids:
                continue

            perimeter = float(sum(v for nid, v in ring_votes.get(cid, {}).items() if nid in info))
            if perimeter <= 0.0:
                perimeter = 1.0

            best_nid = None
            best_score = None
            fallback_nid = None
            fallback_score = None
            area_norm = max(1.0, float(max(int(info[nid]["area"]) for nid in neigh_ids)))

            for nid in neigh_ids:
                key = (cid, nid) if cid < nid else (nid, cid)
                shared_len = float(shared.get(key, 0))
                if shared_len <= 0.0:
                    continue

                surrounding_dominance = float(ring_votes.get(cid, {}).get(nid, 0)) / perimeter
                shared_border_ratio = shared_len / perimeter
                neighbor_area_score = float(info[nid]["area"]) / area_norm

                lab_a = comp_lab.get(cid)
                lab_b = comp_lab.get(nid)
                if lab_a is None or lab_b is None:
                    delta_e_norm = 1.0
                else:
                    delta_e_norm = float(np.linalg.norm(lab_a - lab_b) / 35.0)
                    delta_e_norm = float(np.clip(delta_e_norm, 0.0, 3.0))

                pedge = float(edge_mean.get(key, 0.0) / max(edge_barrier, 1e-6))
                pedge = float(np.clip(pedge, 0.0, 2.0))

                score = (
                    4.0 * shared_border_ratio
                    + 2.0 * surrounding_dominance
                    + 1.0 * neighbor_area_score
                    - 2.0 * delta_e_norm
                    - 2.0 * pedge
                )

                if fallback_score is None or score > fallback_score:
                    fallback_score = score
                    fallback_nid = nid

                if pedge > 1.0:
                    continue

                if best_score is None or score > best_score:
                    best_score = score
                    best_nid = nid

            target_nid = best_nid if best_nid is not None else fallback_nid
            if target_nid is None:
                continue

            target_color = int(info[target_nid]["color"])
            current[mask] = target_color
            changed = True

        if not changed:
            break

    current = _micro_contour_cleanup(current, protected_mask=protected_mask, cfg=cfg)

    after_count, after_avg = _region_summary(current)

    smallest: list[dict[str, float | int]] = []
    comp_map, info = _component_maps(current)
    comp_lab = _component_mean_lab(comp_map, image_lab)
    for cid, cinfo in sorted(info.items(), key=lambda kv: int(kv[1]["area"]))[:20]:
        lab = comp_lab.get(int(cid), np.zeros(3, dtype=np.float32))
        smallest.append(
            {
                "component_id": int(cid),
                "color_label": int(cinfo["color"]),
                "area_px": int(cinfo["area"]),
                "bbox_width_px": int(cinfo["bbox_width"]),
                "bbox_height_px": int(cinfo["bbox_height"]),
                "radius_px": float(cinfo["radius"]),
                "mean_lab_l": float(lab[0]),
                "mean_lab_a": float(lab[1]),
                "mean_lab_b": float(lab[2]),
            }
        )

    return FinalSimplifyResult(
        label_map=current.astype(np.int32),
        unpaintable_regions_mask=unpaintable_mask.astype(np.uint8),
        dense_line_areas_mask=dense_mask.astype(np.uint8),
        region_count_before=int(before_count),
        region_count_after=int(after_count),
        average_region_area_before=float(before_avg),
        average_region_area_after=float(after_avg),
        smallest_region_report=smallest,
    )
