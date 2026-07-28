from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage import color

from .detail_protection import (
    DetailProtection,
    advanced_zone,
    boundary_selection_coverage,
)
from .microregions import build_source_microregions
from .print_spec import PrintSpec
from .segmentation import (
    DETAIL_EDGE_SCALES,
    _boundary_protection_scores,
    _enforce_physical_constraints,
    _protected_edge_mask,
    _adjacency_with_shared_boundary,
    _source_edge_strength,
    region_boundary_evidence,
)


@dataclass(frozen=True)
class HybridGeometryResult:
    label_map: np.ndarray
    boundary_evidence: dict[tuple[int, int], float]
    selection_coverage: dict[tuple[int, int], float]
    metrics: dict[str, object]
    geometry_log: list[dict[str, object]]
    advanced_zone: np.ndarray


def build_hybrid_geometry(
    source_rgb: np.ndarray,
    base_map: np.ndarray,
    protection: DetailProtection,
    print_spec: PrintSpec,
) -> HybridGeometryResult:
    zone = advanced_zone(base_map, protection)
    microregions = build_source_microregions(source_rgb, zone)
    combined = _stitch_maps(base_map, microregions.label_map, zone)
    combined, seam_merges_before_cleanup = collapse_unsupported_seams(source_rgb, combined, zone)
    adjacency, shared = _adjacency_with_shared_boundary(combined)
    source_protection = _boundary_protection_scores(source_rgb, combined, adjacency, shared)
    protected_mask = _protected_edge_mask(combined, source_protection)
    cleaned, cleanup_log = _enforce_physical_constraints(
        source_rgb,
        combined,
        print_spec,
        protected_mask,
        min_area_mm2=0.5,
        min_width_mm=0.5,
        min_label_pocket_mm=0.0,
    )
    cleaned, seam_merges_after_cleanup = collapse_unsupported_seams(source_rgb, cleaned, zone)
    evidence = region_boundary_evidence(source_rgb, cleaned)
    coverage = boundary_selection_coverage(cleaned, protection.weight)
    seam_edge_count = unsupported_seam_edge_count(source_rgb, cleaned, zone)
    metrics = {
        **microregions.metrics,
        "selected_area_percent": protection.coverage_percent,
        "advanced_zone_percent": round(100.0 * float(zone.mean()), 6),
        "base_region_count": int(np.unique(base_map[base_map > 0]).size),
        "hybrid_region_count_before_cleanup": int(np.unique(combined[combined > 0]).size),
        "hybrid_region_count": int(np.unique(cleaned[cleaned > 0]).size),
        "unsupported_transition_merge_count": seam_merges_before_cleanup + seam_merges_after_cleanup,
        "unsupported_transition_edge_count": seam_edge_count,
    }
    return HybridGeometryResult(
        label_map=cleaned,
        boundary_evidence=evidence,
        selection_coverage=coverage,
        metrics=metrics,
        geometry_log=[{"operation": "hybrid_microregion_summary", **metrics}, *cleanup_log],
        advanced_zone=zone,
    )


def _stitch_maps(base_map: np.ndarray, microregion_map: np.ndarray, zone: np.ndarray) -> np.ndarray:
    outside_ids = np.unique(base_map[~zone])
    outside_ids = outside_ids[outside_ids > 0]
    result = np.zeros(base_map.shape, dtype=np.int32)
    for index, region_id in enumerate(outside_ids, start=1):
        result[base_map == region_id] = index
    offset = len(outside_ids)
    result[zone] = microregion_map[zone] + offset
    return _compact_labels(result)


def unsupported_seam_edge_count(
    source_rgb: np.ndarray,
    label_map: np.ndarray,
    zone: np.ndarray,
) -> int:
    return len(_unsupported_seam_pairs(source_rgb, label_map, zone))


def collapse_unsupported_seams(
    source_rgb: np.ndarray,
    label_map: np.ndarray,
    zone: np.ndarray,
) -> tuple[np.ndarray, int]:
    result = label_map
    merge_count = 0
    for _ in range(32):
        pairs = _unsupported_seam_pairs(source_rgb, result, zone)
        if not pairs:
            break
        before = int(np.unique(result[result > 0]).size)
        result = _merge_region_pairs(result, pairs)
        after = int(np.unique(result[result > 0]).size)
        if after >= before:
            break
        merge_count += before - after
    return result, merge_count


def _unsupported_seam_pairs(
    source_rgb: np.ndarray,
    label_map: np.ndarray,
    zone: np.ndarray,
) -> set[tuple[int, int]]:
    edge_strength = _source_edge_strength(source_rgb, DETAIL_EDGE_SCALES)
    edge_values: dict[tuple[int, int], list[float]] = {}
    for left, right, left_zone, right_zone, left_edge, right_edge in (
        (
            label_map[:, :-1],
            label_map[:, 1:],
            zone[:, :-1],
            zone[:, 1:],
            edge_strength[:, :-1],
            edge_strength[:, 1:],
        ),
        (
            label_map[:-1, :],
            label_map[1:, :],
            zone[:-1, :],
            zone[1:, :],
            edge_strength[:-1, :],
            edge_strength[1:, :],
        ),
    ):
        mask = (left != right) & (left > 0) & (right > 0) & (left_zone != right_zone)
        for first, second, value in zip(
            left[mask],
            right[mask],
            np.maximum(left_edge[mask], right_edge[mask]),
            strict=False,
        ):
            pair = (min(int(first), int(second)), max(int(first), int(second)))
            edge_values.setdefault(pair, []).append(float(value))
    if not edge_values:
        return set()

    source_lab = color.rgb2lab(source_rgb.astype(np.float64) / 255.0)
    maximum = int(label_map.max()) + 1
    counts = np.bincount(label_map.ravel(), minlength=maximum).astype(np.float64)
    means = np.zeros((maximum, 3), dtype=np.float64)
    for channel in range(3):
        means[:, channel] = np.bincount(
            label_map.ravel(),
            weights=source_lab[..., channel].ravel(),
            minlength=maximum,
        )
    means[1:] /= np.maximum(counts[1:, None], 1.0)
    pairs = sorted(edge_values)
    left_ids = np.asarray([pair[0] for pair in pairs], dtype=np.int32)
    right_ids = np.asarray([pair[1] for pair in pairs], dtype=np.int32)
    deltas = color.deltaE_ciede2000(means[left_ids], means[right_ids])
    unsupported: set[tuple[int, int]] = set()
    for pair, delta in zip(pairs, deltas, strict=True):
        direct_edge_support = float(np.median(edge_values[pair]))
        source_support = max(min(1.0, float(delta) / 10.0), direct_edge_support)
        if float(delta) < 2.0 and source_support < 0.20:
            unsupported.add(pair)
    return unsupported


def _merge_region_pairs(
    label_map: np.ndarray,
    pairs: set[tuple[int, int]],
) -> np.ndarray:
    maximum = int(label_map.max())
    parent = np.arange(maximum + 1, dtype=np.int32)

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[int(parent[value])]
            value = int(parent[value])
        return value

    for left, right in sorted(pairs):
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            continue
        target, source = (
            (left_root, right_root)
            if left_root < right_root
            else (right_root, left_root)
        )
        parent[source] = target
    roots = np.arange(maximum + 1, dtype=np.int32)
    for region_id in range(1, maximum + 1):
        roots[region_id] = find(region_id)
    return _compact_labels(roots[label_map])


def _compact_labels(label_map: np.ndarray) -> np.ndarray:
    values = np.unique(label_map)
    values = values[values > 0]
    lookup = np.zeros(int(values.max()) + 1, dtype=np.int32)
    lookup[values] = np.arange(1, len(values) + 1, dtype=np.int32)
    return lookup[label_map]
