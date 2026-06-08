from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy import ndimage


@dataclass
class RegionCleanupConfig:
    min_region_area_px: int
    min_region_area_percent: float
    min_region_width_px: int
    min_region_height_px: int
    min_number_radius_px: float
    allow_external_labels: bool
    max_external_labels_percent: float
    shape_cleanup_passes: int
    edge_protection_percentile: float = 82.0
    protected_edge_dilate_px: int = 1
    detail_protection_strength: float = 1.0


@dataclass
class ComponentInfo:
    component_id: int
    color_label: int
    area: int
    bbox_width: int
    bbox_height: int
    mean_lab: np.ndarray
    max_inscribed_radius: float = 0.0


def _compute_component_map(label_map: np.ndarray) -> tuple[np.ndarray, dict[int, ComponentInfo]]:
    h, w = label_map.shape
    comp_map = np.full((h, w), -1, dtype=np.int32)
    infos: dict[int, ComponentInfo] = {}
    next_id = 1

    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        n, cc, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            cid = next_id
            next_id += 1
            comp_map[cc == i] = cid
            infos[cid] = ComponentInfo(
                component_id=cid,
                color_label=int(color),
                area=int(stats[i, cv2.CC_STAT_AREA]),
                bbox_width=int(stats[i, cv2.CC_STAT_WIDTH]),
                bbox_height=int(stats[i, cv2.CC_STAT_HEIGHT]),
                mean_lab=np.zeros(3, dtype=np.float32),
            )

    return comp_map, infos


def _component_neighbors(component_map: np.ndarray) -> dict[int, set[int]]:
    neighbors: dict[int, set[int]] = {}

    def collect(a: np.ndarray, b: np.ndarray) -> None:
        diff = a != b
        if not np.any(diff):
            return
        aa = a[diff].astype(np.int32)
        bb = b[diff].astype(np.int32)
        for left, right in zip(aa.tolist(), bb.tolist()):
            if left <= 0 or right <= 0 or left == right:
                continue
            neighbors.setdefault(left, set()).add(right)
            neighbors.setdefault(right, set()).add(left)

    collect(component_map[:, :-1], component_map[:, 1:])
    collect(component_map[:-1, :], component_map[1:, :])
    return neighbors


def _component_boundary_edge_mean(component_map: np.ndarray, edge_strength: np.ndarray) -> dict[tuple[int, int], float]:
    accum: dict[tuple[int, int], tuple[float, int]] = {}

    def collect(a: np.ndarray, b: np.ndarray, e: np.ndarray) -> None:
        diff = a != b
        if not np.any(diff):
            return
        aa = a[diff].astype(np.int32)
        bb = b[diff].astype(np.int32)
        ee = e[diff].astype(np.float32)
        for left, right, ev in zip(aa.tolist(), bb.tolist(), ee.tolist()):
            if left <= 0 or right <= 0 or left == right:
                continue
            key = (left, right) if left < right else (right, left)
            prev_sum, prev_count = accum.get(key, (0.0, 0))
            accum[key] = (prev_sum + float(ev), prev_count + 1)

    collect(component_map[:, :-1], component_map[:, 1:], 0.5 * (edge_strength[:, :-1] + edge_strength[:, 1:]))
    collect(component_map[:-1, :], component_map[1:, :], 0.5 * (edge_strength[:-1, :] + edge_strength[1:, :]))
    return {k: (v[0] / max(v[1], 1)) for k, v in accum.items()}


def _component_boundary_lengths(component_map: np.ndarray) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}

    def collect(a: np.ndarray, b: np.ndarray) -> None:
        diff = a != b
        if not np.any(diff):
            return
        aa = a[diff].astype(np.int32)
        bb = b[diff].astype(np.int32)
        for left, right in zip(aa.tolist(), bb.tolist()):
            if left <= 0 or right <= 0 or left == right:
                continue
            key = (left, right) if left < right else (right, left)
            counts[key] = counts.get(key, 0) + 1

    collect(component_map[:, :-1], component_map[:, 1:])
    collect(component_map[:-1, :], component_map[1:, :])
    return counts


def _recompute_component_lab(component_map: np.ndarray, image_lab: np.ndarray, infos: dict[int, ComponentInfo]) -> None:
    ids = component_map.ravel()
    for cid, info in infos.items():
        mask = ids == cid
        if not np.any(mask):
            info.mean_lab = np.zeros(3, dtype=np.float32)
            info.area = 0
            continue
        pix = image_lab.reshape(-1, 3)[mask]
        info.mean_lab = pix.mean(axis=0).astype(np.float32)
        info.area = int(mask.sum())


def _recompute_component_radii(component_map: np.ndarray, infos: dict[int, ComponentInfo]) -> None:
    for cid, info in infos.items():
        mask = (component_map == cid).astype(np.uint8)
        if not np.any(mask):
            info.max_inscribed_radius = 0.0
            continue
        dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        _, best, _, _ = cv2.minMaxLoc(dist)
        info.max_inscribed_radius = float(best)


def _minimum_area(total_px: int, cfg: RegionCleanupConfig) -> int:
    return max(cfg.min_region_area_px, int(round(total_px * cfg.min_region_area_percent)))


def _component_mean_map(component_map: np.ndarray, value_map: np.ndarray) -> dict[int, float]:
    ids = component_map.ravel().astype(np.int32)
    vals = value_map.ravel().astype(np.float32)
    valid = ids > 0
    if not np.any(valid):
        return {}
    ids = ids[valid]
    vals = vals[valid]
    sums = np.bincount(ids, weights=vals)
    cnts = np.bincount(ids)
    out: dict[int, float] = {}
    for cid in np.nonzero(cnts)[0].tolist():
        if cid <= 0:
            continue
        out[int(cid)] = float(sums[cid] / max(cnts[cid], 1))
    return out


def _is_invalid_component(info: ComponentInfo, min_area: int, cfg: RegionCleanupConfig) -> bool:
    if int(info.area) < int(min_area):
        return True
    if int(info.bbox_width) < int(cfg.min_region_width_px):
        return True
    if int(info.bbox_height) < int(cfg.min_region_height_px):
        return True
    if float(info.max_inscribed_radius) < float(cfg.min_number_radius_px):
        return True
    return False


def enforce_paintability(
    label_map: np.ndarray,
    image_lab: np.ndarray,
    cfg: RegionCleanupConfig,
    edge_strength: np.ndarray | None = None,
    importance_map: np.ndarray | None = None,
    protected_mask: np.ndarray | None = None,
    max_iter: int = 40,
) -> np.ndarray:
    current = label_map.copy().astype(np.int32)
    min_area = _minimum_area(current.size, cfg)
    edge_barrier = None
    if edge_strength is not None:
        edge_barrier = float(np.percentile(edge_strength, cfg.edge_protection_percentile))

    prot_bool = None if protected_mask is None else (protected_mask > 0)
    for _ in range(max_iter):
        comp_map, infos = _compute_component_map(current)
        if not infos:
            break

        _recompute_component_lab(comp_map, image_lab, infos)
        _recompute_component_radii(comp_map, infos)

        neighbors = _component_neighbors(comp_map)
        boundary_lengths = _component_boundary_lengths(comp_map)
        boundary_edge = _component_boundary_edge_mean(comp_map, edge_strength) if edge_strength is not None else {}
        comp_edge = _component_mean_map(comp_map, edge_strength) if edge_strength is not None else {}
        comp_importance = _component_mean_map(comp_map, importance_map) if importance_map is not None else {}
        comp_protected = _component_mean_map(comp_map, prot_bool.astype(np.float32)) if prot_bool is not None else {}

        invalid_ids = [cid for cid, info in infos.items() if _is_invalid_component(info, min_area, cfg)]
        if not invalid_ids:
            break

        protected_invalid_ids: list[int] = []
        merge_ids: list[int] = []
        for cid in invalid_ids:
            prot_score = float(comp_protected.get(cid, 0.0))
            edge_score = float(comp_edge.get(cid, 0.0))
            importance_score = float(comp_importance.get(cid, 0.0))
            detail_score = 0.45 * prot_score + 0.35 * edge_score + 0.20 * importance_score
            if cfg.allow_external_labels and detail_score >= 0.22 and prot_score >= 0.12:
                protected_invalid_ids.append(cid)
            else:
                merge_ids.append(cid)

        if cfg.allow_external_labels and protected_invalid_ids:
            total_regions = max(1, len(infos))
            max_external = int(np.floor((float(cfg.max_external_labels_percent) / 100.0) * float(total_regions)))
            max_external = max(1, max_external)
            if len(protected_invalid_ids) > max_external:
                ranked = sorted(
                    protected_invalid_ids,
                    key=lambda cid: (
                        -float(comp_protected.get(cid, 0.0)),
                        -float(comp_edge.get(cid, 0.0)),
                        -float(comp_importance.get(cid, 0.0)),
                    ),
                )
                protected_invalid_ids = ranked[:max_external]
                merge_ids.extend(ranked[max_external:])

        if not merge_ids:
            # Only protected details remain and they are eligible for external labeling.
            break

        changed = False
        for cid in sorted(merge_ids, key=lambda x: infos[x].area):
            info = infos.get(cid)
            if info is None or info.area <= 0:
                continue

            candidates = [nid for nid in neighbors.get(cid, set()) if nid in infos and infos[nid].area > 0]
            if not candidates:
                continue

            max_shared = 1
            max_n_area = 1
            for nid in candidates:
                key = (cid, nid) if cid < nid else (nid, cid)
                max_shared = max(max_shared, int(boundary_lengths.get(key, 0)))
                max_n_area = max(max_n_area, int(infos[nid].area))

            best_nid = None
            best_score = None
            for nid in candidates:
                n_info = infos[nid]
                key = (cid, nid) if cid < nid else (nid, cid)
                shared_len = float(boundary_lengths.get(key, 0))
                if shared_len <= 0.0:
                    continue

                color_dist = float(np.linalg.norm(info.mean_lab - n_info.mean_lab))
                color_sim = float(np.exp(-color_dist / 18.0))
                shared_score = float(shared_len / max_shared)

                if edge_strength is not None:
                    b_edge = float(boundary_edge.get(key, 0.0))
                    denom = edge_barrier if edge_barrier is not None and edge_barrier > 1e-6 else 1.0
                    weak_boundary = float(np.clip(1.0 - (b_edge / denom), 0.0, 1.0))
                else:
                    weak_boundary = 0.5

                size_score = float(np.log1p(n_info.area) / np.log1p(max_n_area))
                score = 0.38 * shared_score + 0.30 * color_sim + 0.18 * weak_boundary + 0.14 * size_score

                if best_score is None or score > best_score:
                    best_score = score
                    best_nid = nid

            if best_nid is None:
                continue

            current[comp_map == cid] = int(infos[best_nid].color_label)
            changed = True

        if not changed:
            break

    return current.astype(np.int32)


def merge_tiny_components(
    label_map: np.ndarray,
    image_lab: np.ndarray,
    cfg: RegionCleanupConfig,
    edge_strength: np.ndarray | None = None,
    importance_map: np.ndarray | None = None,
    protected_mask: np.ndarray | None = None,
    max_iter: int = 25,
) -> np.ndarray:
    current = label_map.copy().astype(np.int32)
    min_area = _minimum_area(current.size, cfg)
    edge_barrier = None
    if edge_strength is not None:
        edge_barrier = float(np.percentile(edge_strength, cfg.edge_protection_percentile))

    if protected_mask is not None and cfg.protected_edge_dilate_px > 0:
        k = 2 * cfg.protected_edge_dilate_px + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        protected_mask = cv2.dilate((protected_mask > 0).astype(np.uint8), kernel, iterations=1).astype(bool)

    for _ in range(max_iter):
        comp_map, infos = _compute_component_map(current)
        if not infos:
            break
        _recompute_component_lab(comp_map, image_lab, infos)
        neighbors = _component_neighbors(comp_map)
        boundary_edge = _component_boundary_edge_mean(comp_map, edge_strength) if edge_strength is not None else {}
        comp_edge = _component_mean_map(comp_map, edge_strength) if edge_strength is not None else {}
        comp_importance = _component_mean_map(comp_map, importance_map) if importance_map is not None else {}
        comp_protected = _component_mean_map(comp_map, protected_mask.astype(np.float32)) if protected_mask is not None else {}

        tiny_ids = [cid for cid, info in infos.items() if info.area < min_area]
        if not tiny_ids:
            break

        changed = False
        for cid in sorted(tiny_ids, key=lambda x: infos[x].area):
            info = infos[cid]
            candidates = neighbors.get(cid, set())
            if not candidates:
                continue

            contrast_score = 0.0
            for nid in candidates:
                n_info = infos.get(nid)
                if n_info is None or n_info.area <= 0:
                    continue
                contrast_score = max(contrast_score, float(np.linalg.norm(info.mean_lab - n_info.mean_lab)))

            edge_score = float(comp_edge.get(cid, 0.0))
            importance_score = float(comp_importance.get(cid, 0.0))
            protected_score = float(comp_protected.get(cid, 0.0))
            visual_score = (
                0.42 * np.clip(importance_score, 0.0, 1.0)
                + 0.34 * np.clip(edge_score, 0.0, 1.0)
                + 0.24 * np.clip(contrast_score / 35.0, 0.0, 1.0)
            ) * (1.0 + 0.35 * float(np.clip(cfg.detail_protection_strength, 0.0, 2.5)))

            if visual_score >= 0.46 or protected_score >= 0.22:
                continue

            best_neighbor = None
            best_key = None
            for nid in candidates:
                n_info = infos.get(nid)
                if n_info is None or n_info.area <= 0:
                    continue

                if edge_barrier is not None:
                    key_edge = (cid, nid) if cid < nid else (nid, cid)
                    boundary_mean = float(boundary_edge.get(key_edge, 0.0))
                    if boundary_mean >= edge_barrier:
                        continue

                dist = float(np.linalg.norm(info.mean_lab - n_info.mean_lab))
                # Tie-breaker favors larger neighboring regions.
                key = (dist, -int(n_info.area))
                if best_key is None or key < best_key:
                    best_key = key
                    best_neighbor = n_info

            if best_neighbor is None:
                continue

            current[comp_map == cid] = int(best_neighbor.color_label)
            changed = True

        if not changed:
            break

    return current


def smooth_region_shapes(label_map: np.ndarray, passes: int, protected_mask: np.ndarray | None = None) -> np.ndarray:
    if passes <= 0:
        return label_map

    out = label_map.copy().astype(np.int32)
    protect = None if protected_mask is None else (protected_mask > 0)
    for _ in range(passes):
        # Majority filter removes isolated pixels and tiny holes while preserving larger structure.
        smooth = ndimage.generic_filter(out, lambda x: int(np.bincount(x.astype(np.int32)).argmax()), size=3)
        smooth = cv2.medianBlur(smooth.astype(np.uint8), 3).astype(np.int32)
        if protect is None:
            out = smooth
        else:
            out = np.where(protect, out, smooth).astype(np.int32)

    return out
