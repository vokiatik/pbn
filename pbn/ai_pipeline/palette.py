from __future__ import annotations

from pathlib import Path
from math import ceil

import numpy as np
from scipy import ndimage
from skimage import color
from sklearn.cluster import KMeans
from threadpoolctl import threadpool_limits

from .io_utils import atomic_write_json, save_rgb
from .hierarchical_merge import compact_hierarchically
from .regions import build_adjacency


WEAK_SOURCE_DELTA_E = 2.0
WEAK_BOUNDARY_EVIDENCE = 0.20
HARD_BOUNDARY_EVIDENCE = 0.70
ARTIFICIAL_PAINT_DELTA_E = 5.0
MAX_ALTERNATIVE_ERROR_E = 8.0
MAX_ALTERNATIVE_PENALTY_E = 2.0


def derive_region_palette(
    rgb: np.ndarray,
    region_map: np.ndarray,
    output_dir: Path,
    target_palette_size: int,
    protected_region_ids: set[int] | None = None,
    prefilled_detail_region_ids: set[int] | None = None,
    protection_scores: dict[int, float] | None = None,
    boundary_evidence: dict[tuple[int, int], float] | None = None,
    target_region_count: int | None = None,
    dynamic_compaction: bool = False,
    maximum_region_count: int | None = None,
    user_protected_pairs: set[tuple[int, int]] | None = None,
    minimum_area_pixels: float = 0.0,
    minimum_width_pixels: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, dict[int, int], list[tuple[int, int, int]], list[dict[str, object]]]:
    """Cluster region colours in Lab and produce a paintable adjacency map.

    A density target preserves the most meaningful source boundaries and colours the
    resulting graph with the requested palette. Calls without a density target retain
    the legacy behaviour used when rebuilding older saved options.
    """
    region_ids = [int(value) for value in np.unique(region_map) if int(value)]
    if not region_ids:
        raise ValueError("cannot derive a palette from an empty region map")
    target = max(1, int(target_palette_size))
    protected_region_ids = set(protected_region_ids or set())
    prefilled_detail_region_ids = set(prefilled_detail_region_ids or set())
    protection_scores = dict(protection_scores or {})
    boundary_evidence = dict(boundary_evidence or {})
    fidelity_metrics: dict[str, object] = {
        "weak_boundary_merge_count": 0,
        "density_merge_count": 0,
        "palette_conflict_merge_count": 0,
        "faithful_alternative_colour_count": 0,
        "artificial_boundary_count": 0,
        "selected_forced_merge_count": 0,
        "palette_protected_forced_merge_count": 0,
        "palette_protected_forced_merges": [],
    }

    source_lab = color.rgb2lab(rgb.astype(np.float64) / 255.0)
    region_lab: list[np.ndarray] = []
    region_areas: list[int] = []
    source_objects = ndimage.find_objects(region_map)
    for region_id in region_ids:
        region_slice = source_objects[region_id - 1]
        if region_slice is None:
            raise ValueError(f"region {region_id} has no pixels")
        mask = region_map[region_slice] == region_id
        region_lab.append(np.median(source_lab[region_slice][mask], axis=0))
        region_areas.append(int(mask.sum()))
    samples = np.asarray(region_lab, dtype=np.float64)
    weights = np.sqrt(np.asarray(region_areas, dtype=np.float64))
    weights *= np.asarray(
        [1.0 + 2.0 * float(np.clip(protection_scores.get(region_id, 0.0), 0.0, 1.0)) for region_id in region_ids],
        dtype=np.float64,
    )

    reserved_indices = _reserved_detail_indices(
        region_ids,
        samples,
        protected_region_ids | prefilled_detail_region_ids,
        protection_scores,
        maximum=min(target - 1, min(8, max(4, ceil(target * 0.25)))),
    )
    reserved_centers = samples[reserved_indices] if reserved_indices else np.empty((0, 3), dtype=np.float64)
    regular_indices = [index for index in range(len(region_ids)) if index not in reserved_indices]
    unique_samples = np.unique(np.round(samples[regular_indices] if regular_indices else samples, decimals=5), axis=0)
    regular_cluster_count = min(max(0, target - len(reserved_indices)), len(regular_indices), len(unique_samples))
    if regular_cluster_count == 0:
        regular_labels = np.empty(0, dtype=np.int32)
        regular_centers = np.empty((0, 3), dtype=np.float64)
    elif regular_cluster_count == 1:
        regular_labels = np.zeros(len(regular_indices), dtype=np.int32)
        regular_centers = np.average(samples[regular_indices], axis=0, weights=weights[regular_indices])[None, :]
    else:
        model = KMeans(n_clusters=regular_cluster_count, random_state=0, n_init=20, algorithm="lloyd")
        # Parallel floating-point reductions can move near-tie samples between
        # clusters across otherwise identical worker processes. Palette clustering
        # is small, so pin only this numerical section to one thread.
        with threadpool_limits(limits=1):
            regular_labels = model.fit_predict(
                samples[regular_indices],
                sample_weight=weights[regular_indices],
            ).astype(np.int32)
        regular_centers = model.cluster_centers_

    centers = np.vstack([regular_centers, reserved_centers])
    cluster_count = len(centers)
    raw_labels = np.zeros(len(region_ids), dtype=np.int32)
    for index, label in zip(regular_indices, regular_labels, strict=True):
        raw_labels[index] = int(label)
    for offset, index in enumerate(reserved_indices):
        raw_labels[index] = regular_cluster_count + offset
    if cluster_count == 1 and len(region_ids):
        raw_labels = np.zeros(len(region_ids), dtype=np.int32)

    # KMeans cluster ids are arbitrary. Sorting makes palette numbering stable.
    order = sorted(range(cluster_count), key=lambda index: tuple(float(v) for v in centers[index]))
    # Reserved detail centres and ordinary clusters can represent the same
    # exported paint. Collapse identical and perceptually indistinguishable
    # paints before adjacency resolution, using the same Delta-E floor as
    # weak source boundaries, to avoid invisible seams and redundant numbers.
    paint_to_cluster: dict[tuple[int, int, int], int] = {}
    unique_order: list[int] = []
    normalized_cluster: dict[int, int] = {}
    for index in order:
        paint = _lab_to_rgb(centers[index])
        if paint not in paint_to_cluster:
            distances = color.deltaE_ciede2000(centers[index][None, :], centers[unique_order])
            if len(distances) and float(distances.min()) < WEAK_SOURCE_DELTA_E:
                paint_to_cluster[paint] = int(np.argmin(distances))
            else:
                paint_to_cluster[paint] = len(unique_order)
                unique_order.append(index)
        normalized_cluster[index] = paint_to_cluster[paint]
    labels = np.asarray([normalized_cluster[int(value)] for value in raw_labels], dtype=np.int32)
    ordered_centers = centers[unique_order]
    initial_region_to_cluster = dict(zip(region_ids, (int(value) for value in labels), strict=True))

    detail_ids = protected_region_ids | prefilled_detail_region_ids
    if target_region_count is None:
        _separate_protected_same_colour_neighbours(
            region_map,
            initial_region_to_cluster,
            samples,
            region_ids,
            ordered_centers,
            detail_ids,
        )
        merged_map = _merge_same_colour_adjacencies(
            region_map,
            initial_region_to_cluster,
            detail_ids,
        )
        region_to_cluster = _majority_clusters_for_merged_map(
            region_map,
            merged_map,
            initial_region_to_cluster,
        )
    else:
        if dynamic_compaction:
            dynamic = compact_hierarchically(
                rgb,
                region_map,
                ordered_centers,
                protection_scores,
                boundary_evidence,
                max(1, int(target_region_count)),
                max(1, int(maximum_region_count or target_region_count)),
                user_protected_pairs=user_protected_pairs,
                minimum_area_pixels=minimum_area_pixels,
                minimum_width_pixels=minimum_width_pixels,
            )
            merged_map = dynamic.label_map
            merged_lab = dynamic.region_lab
            merged_protection = dynamic.protection_scores
            compaction_metrics = dynamic.metrics
        else:
            merged_map, merged_lab, merged_protection, compaction_metrics = _compact_to_density_target(
                region_map,
                samples,
                np.asarray(region_areas, dtype=np.float64),
                initial_region_to_cluster,
                detail_ids,
                protection_scores,
                boundary_evidence,
                ordered_centers,
                max(1, int(target_region_count)),
            )
        merged_evidence = _remap_boundary_evidence(region_map, merged_map, boundary_evidence)
        merged_detail_ids = _remap_region_ids(region_map, merged_map, detail_ids)
        merged_user_pairs = _remap_boundary_pairs(
            region_map,
            merged_map,
            set(user_protected_pairs or set()),
        )
        merged_map, region_to_cluster, resolution_metrics = _resolve_palette_adjacency(
            merged_map,
            merged_lab,
            ordered_centers,
            merged_protection,
            merged_evidence,
            merged_detail_ids,
            merged_user_pairs,
        )
        fidelity_metrics.update(compaction_metrics)
        fidelity_metrics.update(resolution_metrics)
        fidelity_metrics["selected_forced_merge_count"] = int(
            compaction_metrics.get("selected_forced_merge_count", 0)
        ) + int(resolution_metrics.get("selected_forced_merge_count", 0))

    merged_ids = [int(value) for value in np.unique(merged_map) if int(value)]

    active_clusters = sorted(set(region_to_cluster.values()))
    cluster_to_color = {cluster_id: index + 1 for index, cluster_id in enumerate(active_clusters)}
    region_to_color = {
        region_id: cluster_to_color[cluster_id]
        for region_id, cluster_id in region_to_cluster.items()
    }
    palette_rgb = [_lab_to_rgb(ordered_centers[cluster_id]) for cluster_id in active_clusters]

    painted_lut = np.full((int(merged_map.max()) + 1, 3), 255, dtype=np.uint8)
    assignments: list[dict[str, object]] = []
    for region_id in merged_ids:
        color_id = region_to_color[region_id]
        rgb_value = palette_rgb[color_id - 1]
        painted_lut[region_id] = rgb_value
        assignments.append(
            {
                "region_id": region_id,
                "color_id": color_id,
                "palette_rgb": list(rgb_value),
            }
        )

    painted = painted_lut[merged_map]
    output_dir.mkdir(parents=True, exist_ok=True)
    save_rgb(output_dir / "preview.png", painted)
    atomic_write_json(
        output_dir / "palette.json",
        [
            {"color_id": index + 1, "rgb": list(rgb_value)}
            for index, rgb_value in enumerate(palette_rgb)
        ],
    )
    atomic_write_json(output_dir / "region_colours.json", assignments)
    atomic_write_json(output_dir / "fidelity_metrics.json", fidelity_metrics)
    return merged_map, painted, region_to_color, palette_rgb, assignments


def reconcile_palette_after_alignment(
    rgb: np.ndarray,
    region_map: np.ndarray,
    palette_rgb: list[tuple[int, int, int]],
    protected_region_ids: set[int],
    protection_scores: dict[int, float],
    boundary_evidence: dict[tuple[int, int], float],
    user_protected_pairs: set[tuple[int, int]],
) -> tuple[np.ndarray, dict[int, int], dict[str, object]]:
    """Recheck palette topology after geometry alignment changes region samples."""
    source_lab = color.rgb2lab(rgb.astype(np.float64) / 255.0)
    region_lab: dict[int, np.ndarray] = {}
    for region_id, region_slice in enumerate(ndimage.find_objects(region_map), start=1):
        if region_slice is None:
            continue
        mask = region_map[region_slice] == region_id
        region_lab[region_id] = np.median(source_lab[region_slice][mask], axis=0)
    palette_values = np.asarray(palette_rgb, dtype=np.uint8)
    palette_lab = color.rgb2lab(palette_values[:, None, :].astype(np.float64) / 255.0)[:, 0, :]
    resolved_map, region_to_cluster, metrics = _resolve_palette_adjacency(
        region_map,
        region_lab,
        palette_lab,
        protection_scores,
        boundary_evidence,
        protected_region_ids,
        user_protected_pairs,
    )
    return (
        resolved_map,
        {region_id: cluster_id + 1 for region_id, cluster_id in region_to_cluster.items()},
        metrics,
    )


def _majority_clusters_for_merged_map(
    source_map: np.ndarray,
    merged_map: np.ndarray,
    source_clusters: dict[int, int],
) -> dict[int, int]:
    result: dict[int, int] = {}
    merged_ids = [int(value) for value in np.unique(merged_map) if int(value)]
    merged_objects = ndimage.find_objects(merged_map)
    for merged_id in merged_ids:
        region_slice = merged_objects[merged_id - 1]
        if region_slice is None:
            raise ValueError(f"merged region {merged_id} has no pixels")
        merged_mask = merged_map[region_slice] == merged_id
        original_ids, counts = np.unique(source_map[region_slice][merged_mask], return_counts=True)
        cluster_weights: dict[int, int] = {}
        for original_id, count in zip(original_ids, counts, strict=True):
            if not int(original_id):
                continue
            cluster_id = source_clusters[int(original_id)]
            cluster_weights[cluster_id] = cluster_weights.get(cluster_id, 0) + int(count)
        result[merged_id] = max(cluster_weights, key=lambda item: (cluster_weights[item], -item))
    return result


def _compact_to_density_target(
    region_map: np.ndarray,
    samples: np.ndarray,
    region_areas: np.ndarray,
    region_to_cluster: dict[int, int],
    protected_region_ids: set[int],
    protection_scores: dict[int, float],
    boundary_evidence: dict[tuple[int, int], float],
    palette_lab: np.ndarray,
    target_region_count: int,
) -> tuple[np.ndarray, dict[int, np.ndarray], dict[int, float], dict[str, object]]:
    """Remove unsupported boundaries, then compact only as needed by the ceiling."""
    region_ids = sorted(region_to_cluster)
    maximum = int(region_map.max())
    parent = np.arange(maximum + 1, dtype=np.int32)
    protected = np.zeros(maximum + 1, dtype=bool)
    for region_id in protected_region_ids:
        if 0 < region_id <= maximum:
            protected[region_id] = True

    sample_by_id = {region_id: samples[index] for index, region_id in enumerate(region_ids)}
    area_by_id = {region_id: float(region_areas[index]) for index, region_id in enumerate(region_ids)}
    shared_boundaries = _shared_boundary_lengths(region_map)

    def find(region_id: int) -> int:
        while parent[region_id] != region_id:
            parent[region_id] = parent[int(parent[region_id])]
            region_id = int(parent[region_id])
        return region_id

    edges: list[dict[str, float | int | bool]] = []
    for (left, right), shared in shared_boundaries.items():
        if left not in region_to_cluster or right not in region_to_cluster:
            continue
        delta = float(color.deltaE_ciede2000(sample_by_id[left][None, :], sample_by_id[right][None, :])[0])
        evidence = float(
            boundary_evidence.get(
                (left, right),
                max(protection_scores.get(left, 0.0), protection_scores.get(right, 0.0)),
            )
        )
        contact = shared / max(1.0, np.sqrt(min(area_by_id[left], area_by_id[right])))
        total_area = area_by_id[left] + area_by_id[right]
        merged_sample = (
            sample_by_id[left] * area_by_id[left] + sample_by_id[right] * area_by_id[right]
        ) / max(1.0, total_area)
        merged_error = float(np.min(color.deltaE_ciede2000(merged_sample[None, :], palette_lab)))
        separate_error = (
            float(
                color.deltaE_ciede2000(
                    sample_by_id[left][None, :],
                    palette_lab[region_to_cluster[left]][None, :],
                )[0]
            )
            * area_by_id[left]
            + float(
                color.deltaE_ciede2000(
                    sample_by_id[right][None, :],
                    palette_lab[region_to_cluster[right]][None, :],
                )[0]
            )
            * area_by_id[right]
        ) / max(1.0, total_area)
        edges.append(
            {
                "left": left,
                "right": right,
                "delta": delta,
                "evidence": evidence,
                "reconstruction_loss": max(0.0, merged_error - separate_error),
                "shape_loss": abs(area_by_id[left] - area_by_id[right]) / max(1.0, total_area),
                "contact": contact,
                "weak": delta < WEAK_SOURCE_DELTA_E and evidence < WEAK_BOUNDARY_EVIDENCE,
            }
        )

    weak_edges = sorted(
        (edge for edge in edges if bool(edge["weak"])),
        key=lambda edge: (
            float(edge["evidence"]),
            float(edge["reconstruction_loss"]),
            float(edge["delta"]),
            -float(edge["contact"]),
            int(edge["left"]),
            int(edge["right"]),
        ),
    )
    density_edges = sorted(
        edges,
        key=lambda edge: (
            float(edge["reconstruction_loss"]),
            float(edge["evidence"]),
            float(edge["delta"]),
            float(edge["shape_loss"]),
            -float(edge["contact"]),
            int(edge["left"]),
            int(edge["right"]),
        ),
    )

    active_count = len(region_ids)
    weak_merge_count = 0
    density_merge_count = 0

    def merge_edge(edge: dict[str, float | int | bool]) -> bool:
        nonlocal active_count
        left, right = int(edge["left"]), int(edge["right"])
        left_root, right_root = find(left), find(right)
        if left_root == right_root or float(edge["evidence"]) >= HARD_BOUNDARY_EVIDENCE:
            return False
        target, source = (left_root, right_root) if left_root < right_root else (right_root, left_root)
        parent[source] = target
        protected[target] = protected[target] or protected[source]
        active_count -= 1
        return True

    for edge in weak_edges:
        if merge_edge(edge):
            weak_merge_count += 1
    for edge in density_edges:
        if active_count <= target_region_count:
            break
        if merge_edge(edge):
            density_merge_count += 1

    roots = np.arange(maximum + 1, dtype=np.int32)
    for region_id in region_ids:
        roots[region_id] = find(region_id)
    rooted = roots[region_map]
    active_roots = np.unique(rooted)
    active_roots = active_roots[active_roots > 0]
    root_to_compact = {int(root): index + 1 for index, root in enumerate(active_roots)}
    compact_lut = np.zeros(maximum + 1, dtype=np.int32)
    for region_id in region_ids:
        compact_lut[region_id] = root_to_compact[find(region_id)]
    compacted = compact_lut[region_map]

    lab_sums: dict[int, np.ndarray] = {}
    area_sums: dict[int, float] = {}
    merged_protection: dict[int, float] = {}
    for region_id in region_ids:
        merged_id = root_to_compact[find(region_id)]
        area = area_by_id[region_id]
        lab_sums[merged_id] = lab_sums.get(merged_id, np.zeros(3, dtype=np.float64)) + sample_by_id[region_id] * area
        area_sums[merged_id] = area_sums.get(merged_id, 0.0) + area
        merged_protection[merged_id] = max(
            merged_protection.get(merged_id, 0.0),
            protection_scores.get(region_id, 0.0),
            1.0 if region_id in protected_region_ids else 0.0,
        )
    merged_lab = {region_id: lab_sums[region_id] / area_sums[region_id] for region_id in lab_sums}
    return compacted, merged_lab, merged_protection, {
        "initial_region_count": len(region_ids),
        "density_ceiling": int(target_region_count),
        "weak_boundary_merge_count": weak_merge_count,
        "density_merge_count": density_merge_count,
        "post_compaction_region_count": len(merged_lab),
    }


def _resolve_palette_adjacency(
    region_map: np.ndarray,
    region_lab: dict[int, np.ndarray],
    palette_lab: np.ndarray,
    protection_scores: dict[int, float],
    boundary_evidence: dict[tuple[int, int], float],
    protected_region_ids: set[int],
    user_protected_pairs: set[tuple[int, int]] | None = None,
) -> tuple[np.ndarray, dict[int, int], dict[str, object]]:
    """Resolve adjacency without inventing contrast solely to preserve density."""
    faithful_recolours = 0
    conflict_merges = 0
    selected_forced_merges = 0
    protected_forced_merges: list[dict[str, object]] = []
    current_map = region_map
    current_lab = dict(region_lab)
    current_protection = dict(protection_scores)
    current_evidence = dict(boundary_evidence)
    current_protected = set(protected_region_ids)
    current_user_pairs = set(user_protected_pairs or set())

    for _ in range(max(1, len(current_lab))):
        assigned = {
            region_id: int(np.argmin(color.deltaE_ciede2000(value[None, :], palette_lab)))
            for region_id, value in current_lab.items()
        }
        adjacency = build_adjacency(current_map)

        for left in sorted(adjacency):
            for right in sorted(adjacency[left]):
                if right <= left or assigned[left] != assigned[right]:
                    continue
                alternative = _faithful_alternative_assignment(
                    left,
                    right,
                    assigned,
                    adjacency,
                    current_lab,
                    palette_lab,
                    current_evidence,
                    current_protection,
                )
                if alternative is not None:
                    region_id, colour_id = alternative
                    assigned[region_id] = colour_id
                    faithful_recolours += 1

        violations: list[tuple[float, float, float, int, int]] = []
        artificial_count = 0
        for left in sorted(adjacency):
            for right in sorted(adjacency[left]):
                if right <= left:
                    continue
                pair = (left, right)
                source_delta = float(color.deltaE_ciede2000(current_lab[left][None, :], current_lab[right][None, :])[0])
                evidence = float(
                    current_evidence.get(
                        pair,
                        max(current_protection.get(left, 0.0), current_protection.get(right, 0.0)),
                    )
                )
                paint_delta = float(
                    color.deltaE_ciede2000(
                        palette_lab[assigned[left]][None, :],
                        palette_lab[assigned[right]][None, :],
                    )[0]
                )
                same_paint = assigned[left] == assigned[right]
                artificial = (
                    source_delta < WEAK_SOURCE_DELTA_E
                    and evidence < WEAK_BOUNDARY_EVIDENCE
                    and paint_delta >= ARTIFICIAL_PAINT_DELTA_E
                )
                if artificial:
                    artificial_count += 1
                if same_paint or artificial:
                    violations.append((evidence, source_delta, paint_delta, left, right))

        if not violations:
            return current_map, assigned, {
                "palette_conflict_merge_count": conflict_merges,
                "faithful_alternative_colour_count": faithful_recolours,
                "artificial_boundary_count": 0,
                "selected_forced_merge_count": selected_forced_merges,
                "palette_protected_forced_merge_count": len(protected_forced_merges),
                "palette_protected_forced_merges": protected_forced_merges,
            }

        merge_pairs: list[tuple[int, int]] = []
        selected_forced_pairs: set[tuple[int, int]] = set()
        occupied: set[int] = set()
        for _, _, _, left, right in sorted(violations):
            if left in occupied or right in occupied:
                continue
            pair = (min(left, right), max(left, right))
            is_selected_pair = pair in current_user_pairs
            if current_evidence.get(pair, 0.0) >= HARD_BOUNDARY_EVIDENCE and not is_selected_pair:
                continue
            merge_pairs.append((left, right))
            if is_selected_pair:
                selected_forced_pairs.add(pair)
            occupied.update((left, right))
        if not merge_pairs:
            region_areas = np.bincount(
                current_map.ravel(),
                minlength=int(current_map.max()) + 1,
            )
            fallback_candidates = [
                _protected_palette_merge_candidate(
                    region_areas,
                    current_lab,
                    palette_lab,
                    assigned,
                    evidence,
                    source_delta,
                    paint_delta,
                    left,
                    right,
                    current_user_pairs,
                )
                for evidence, source_delta, paint_delta, left, right in violations
            ]
            _, fallback = min(
                fallback_candidates,
                key=lambda item: item[0],
            )
            left = int(fallback["left_region_id"])
            right = int(fallback["right_region_id"])
            merge_pairs.append((left, right))
            protected_forced_merges.append(fallback)

        previous_map = current_map
        current_map = _merge_region_pairs(previous_map, merge_pairs)
        current_lab = _remap_region_lab(previous_map, current_map, current_lab)
        current_protection = _remap_region_scores(previous_map, current_map, current_protection)
        current_evidence = _remap_boundary_evidence(previous_map, current_map, current_evidence)
        current_protected = _remap_region_ids(previous_map, current_map, current_protected)
        current_user_pairs = _remap_boundary_pairs(previous_map, current_map, current_user_pairs)
        conflict_merges += len(merge_pairs)
        selected_forced_merges += len(selected_forced_pairs)

    raise ValueError("palette adjacency resolution did not converge")


def _protected_palette_merge_candidate(
    region_areas: np.ndarray,
    region_lab: dict[int, np.ndarray],
    palette_lab: np.ndarray,
    assigned: dict[int, int],
    evidence: float,
    source_delta: float,
    paint_delta: float,
    left: int,
    right: int,
    user_protected_pairs: set[tuple[int, int]],
) -> tuple[tuple[float, float, float, int, int], dict[str, object]]:
    """Describe and rank a last-resort protected palette merge."""
    left_area = float(region_areas[left])
    right_area = float(region_areas[right])
    total_area = max(1.0, left_area + right_area)
    separate_error = (
        float(
            color.deltaE_ciede2000(
                region_lab[left][None, :],
                palette_lab[assigned[left]][None, :],
            )[0]
        )
        * left_area
        + float(
            color.deltaE_ciede2000(
                region_lab[right][None, :],
                palette_lab[assigned[right]][None, :],
            )[0]
        )
        * right_area
    ) / total_area
    merged_sample = (
        region_lab[left] * left_area + region_lab[right] * right_area
    ) / total_area
    merged_error = float(np.min(color.deltaE_ciede2000(merged_sample[None, :], palette_lab)))
    reconstruction_loss = max(0.0, merged_error - separate_error)
    pair = (min(left, right), max(left, right))
    details: dict[str, object] = {
        "left_region_id": left,
        "right_region_id": right,
        "boundary_evidence": round(float(evidence), 6),
        "source_delta_e_00": round(float(source_delta), 6),
        "paint_delta_e_00": round(float(paint_delta), 6),
        "reconstruction_loss_delta_e_00": round(reconstruction_loss, 6),
        "same_palette_colour": assigned[left] == assigned[right],
        "user_selected_boundary": pair in user_protected_pairs,
    }
    return (
        reconstruction_loss,
        float(evidence),
        float(source_delta),
        left,
        right,
    ), details


def _faithful_alternative_assignment(
    left: int,
    right: int,
    assigned: dict[int, int],
    adjacency: dict[int, set[int]],
    region_lab: dict[int, np.ndarray],
    palette_lab: np.ndarray,
    boundary_evidence: dict[tuple[int, int], float],
    protection_scores: dict[int, float],
) -> tuple[int, int] | None:
    candidates: list[tuple[float, int, int]] = []
    for region_id, conflict_id in ((left, right), (right, left)):
        pair = (min(region_id, conflict_id), max(region_id, conflict_id))
        source_delta = float(
            color.deltaE_ciede2000(region_lab[region_id][None, :], region_lab[conflict_id][None, :])[0]
        )
        evidence = float(
            boundary_evidence.get(
                pair,
                max(protection_scores.get(region_id, 0.0), protection_scores.get(conflict_id, 0.0)),
            )
        )
        if source_delta < WEAK_SOURCE_DELTA_E and evidence < WEAK_BOUNDARY_EVIDENCE:
            continue
        distances = color.deltaE_ciede2000(region_lab[region_id][None, :], palette_lab)
        nearest_error = float(np.min(distances))
        forbidden = {assigned[neighbour] for neighbour in adjacency.get(region_id, set())}
        for colour_id, value in enumerate(distances):
            error = float(value)
            if colour_id in forbidden or error > MAX_ALTERNATIVE_ERROR_E or error > nearest_error + MAX_ALTERNATIVE_PENALTY_E:
                continue
            faithful = True
            for neighbour in adjacency.get(region_id, set()):
                neighbour_pair = (min(region_id, neighbour), max(region_id, neighbour))
                neighbour_source_delta = float(
                    color.deltaE_ciede2000(region_lab[region_id][None, :], region_lab[neighbour][None, :])[0]
                )
                paint_delta = float(
                    color.deltaE_ciede2000(
                        palette_lab[colour_id][None, :], palette_lab[assigned[neighbour]][None, :]
                    )[0]
                )
                contrast_limit = max(ARTIFICIAL_PAINT_DELTA_E, 1.5 * neighbour_source_delta + 2.0)
                if paint_delta > contrast_limit + 1e-6:
                    faithful = False
                    break
                neighbour_evidence = float(
                    boundary_evidence.get(
                        neighbour_pair,
                        max(protection_scores.get(region_id, 0.0), protection_scores.get(neighbour, 0.0)),
                    )
                )
                if (
                    neighbour_source_delta < WEAK_SOURCE_DELTA_E
                    and neighbour_evidence < WEAK_BOUNDARY_EVIDENCE
                    and paint_delta >= ARTIFICIAL_PAINT_DELTA_E
                ):
                    faithful = False
                    break
            if faithful:
                candidates.append((error, region_id, colour_id))
    if not candidates:
        return None
    _, region_id, colour_id = min(candidates)
    return region_id, colour_id


def _merge_region_pairs(region_map: np.ndarray, pairs: list[tuple[int, int]]) -> np.ndarray:
    maximum = int(region_map.max())
    parent = np.arange(maximum + 1, dtype=np.int32)

    def find(region_id: int) -> int:
        while parent[region_id] != region_id:
            parent[region_id] = parent[int(parent[region_id])]
            region_id = int(parent[region_id])
        return region_id

    for left, right in pairs:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            continue
        target, source = (left_root, right_root) if left_root < right_root else (right_root, left_root)
        parent[source] = target
    roots = np.asarray([find(index) for index in range(maximum + 1)], dtype=np.int32)
    rooted = roots[region_map]
    active = np.unique(rooted)
    active = active[active > 0]
    compact = np.zeros(maximum + 1, dtype=np.int32)
    compact[active] = np.arange(1, len(active) + 1, dtype=np.int32)
    return compact[rooted]


def _region_remap(source_map: np.ndarray, target_map: np.ndarray) -> dict[int, int]:
    source_ids, first_indices = np.unique(source_map.ravel(), return_index=True)
    target_flat = target_map.ravel()
    return {
        int(source_id): int(target_flat[index])
        for source_id, index in zip(source_ids, first_indices, strict=True)
        if int(source_id) > 0
    }


def _remap_region_ids(source_map: np.ndarray, target_map: np.ndarray, region_ids: set[int]) -> set[int]:
    remap = _region_remap(source_map, target_map)
    return {remap[region_id] for region_id in region_ids if region_id in remap}


def _remap_region_scores(
    source_map: np.ndarray,
    target_map: np.ndarray,
    scores: dict[int, float],
) -> dict[int, float]:
    remap = _region_remap(source_map, target_map)
    result: dict[int, float] = {}
    for source_id, target_id in remap.items():
        result[target_id] = max(result.get(target_id, 0.0), float(scores.get(source_id, 0.0)))
    return result


def _remap_region_lab(
    source_map: np.ndarray,
    target_map: np.ndarray,
    values: dict[int, np.ndarray],
) -> dict[int, np.ndarray]:
    remap = _region_remap(source_map, target_map)
    areas = np.bincount(source_map.ravel(), minlength=int(source_map.max()) + 1).astype(np.float64)
    sums: dict[int, np.ndarray] = {}
    weights: dict[int, float] = {}
    for source_id, target_id in remap.items():
        area = float(areas[source_id])
        sums[target_id] = sums.get(target_id, np.zeros(3, dtype=np.float64)) + values[source_id] * area
        weights[target_id] = weights.get(target_id, 0.0) + area
    return {target_id: sums[target_id] / weights[target_id] for target_id in sums}


def _remap_boundary_evidence(
    source_map: np.ndarray,
    target_map: np.ndarray,
    evidence: dict[tuple[int, int], float],
) -> dict[tuple[int, int], float]:
    remap = _region_remap(source_map, target_map)
    result: dict[tuple[int, int], float] = {}
    for (left, right), score in evidence.items():
        if left not in remap or right not in remap:
            continue
        target_left, target_right = remap[left], remap[right]
        if target_left == target_right:
            continue
        pair = (min(target_left, target_right), max(target_left, target_right))
        result[pair] = max(result.get(pair, 0.0), float(score))
    return result


def _remap_boundary_pairs(
    source_map: np.ndarray,
    target_map: np.ndarray,
    pairs: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    remap = _region_remap(source_map, target_map)
    result: set[tuple[int, int]] = set()
    for left, right in pairs:
        if left not in remap or right not in remap:
            continue
        target_left, target_right = remap[left], remap[right]
        if target_left == target_right:
            continue
        result.add((min(target_left, target_right), max(target_left, target_right)))
    return result


def _shared_boundary_lengths(region_map: np.ndarray) -> dict[tuple[int, int], int]:
    shared: dict[tuple[int, int], int] = {}
    for left_values, right_values in (
        (region_map[:, :-1], region_map[:, 1:]),
        (region_map[:-1, :], region_map[1:, :]),
    ):
        mask = (left_values != right_values) & (left_values > 0) & (right_values > 0)
        left = left_values[mask]
        right = right_values[mask]
        for first, second in zip(left, right, strict=True):
            pair = (int(min(first, second)), int(max(first, second)))
            shared[pair] = shared.get(pair, 0) + 1
    return shared


def _merge_same_colour_adjacencies(
    region_map: np.ndarray,
    region_to_cluster: dict[int, int],
    protected_region_ids: set[int] | None = None,
) -> np.ndarray:
    protected_region_ids = protected_region_ids or set()
    max_region_id = int(region_map.max())
    parent = np.arange(max_region_id + 1, dtype=np.int32)

    def find(region_id: int) -> int:
        while parent[region_id] != region_id:
            parent[region_id] = parent[int(parent[region_id])]
            region_id = int(parent[region_id])
        return region_id

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        target, source = (left_root, right_root) if left_root < right_root else (right_root, left_root)
        parent[source] = target

    for left, neighbours in build_adjacency(region_map).items():
        for right in neighbours:
            if (
                right > left
                and region_to_cluster[left] == region_to_cluster[right]
                and left not in protected_region_ids
                and right not in protected_region_ids
            ):
                union(left, right)

    roots = np.asarray([find(index) for index in range(max_region_id + 1)], dtype=np.int32)
    rooted = roots[region_map]
    active_roots = np.unique(rooted)
    active_roots = active_roots[active_roots > 0]
    compact = np.zeros(int(active_roots.max()) + 1, dtype=np.int32)
    compact[active_roots] = np.arange(1, len(active_roots) + 1, dtype=np.int32)
    return compact[rooted]


def _reserved_detail_indices(
    region_ids: list[int],
    samples: np.ndarray,
    detail_ids: set[int],
    protection_scores: dict[int, float],
    maximum: int,
) -> list[int]:
    candidates = sorted(
        (index for index, region_id in enumerate(region_ids) if region_id in detail_ids),
        key=lambda index: (-protection_scores.get(region_ids[index], 0.0), region_ids[index]),
    )
    selected: list[int] = []
    remaining = list(candidates)
    while remaining and len(selected) < maximum:
        if not selected:
            selected.append(remaining.pop(0))
            continue
        scored: list[tuple[float, float, int, int]] = []
        for index in remaining:
            distances = color.deltaE_ciede2000(samples[index][None, :], samples[selected])
            scored.append(
                (
                    float(np.min(distances)),
                    protection_scores.get(region_ids[index], 0.0),
                    -region_ids[index],
                    index,
                )
            )
        distance, _, _, index = max(scored)
        if distance <= 4.0:
            break
        selected.append(index)
        remaining.remove(index)
    return selected


def _separate_protected_same_colour_neighbours(
    region_map: np.ndarray,
    region_to_cluster: dict[int, int],
    samples: np.ndarray,
    region_ids: list[int],
    centers: np.ndarray,
    protected_ids: set[int],
) -> None:
    sample_by_id = {region_id: samples[index] for index, region_id in enumerate(region_ids)}
    adjacency = build_adjacency(region_map)
    for _ in range(max(1, len(protected_ids))):
        changed = False
        for left in sorted(adjacency):
            for right in sorted(adjacency[left]):
                if right <= left or region_to_cluster[left] != region_to_cluster[right]:
                    continue
                if left not in protected_ids and right not in protected_ids:
                    continue
                target = right if right in protected_ids else left
                forbidden = {
                    region_to_cluster[neighbour]
                    for neighbour in adjacency[target]
                    if neighbour in region_to_cluster
                    and (target in protected_ids or neighbour in protected_ids)
                }
                alternatives = [index for index in range(len(centers)) if index not in forbidden]
                if not alternatives:
                    continue
                distances = color.deltaE_ciede2000(sample_by_id[target][None, :], centers[alternatives])
                region_to_cluster[target] = alternatives[int(np.argmin(distances))]
                changed = True
        if not changed:
            break


def _lab_to_rgb(lab_value: np.ndarray) -> tuple[int, int, int]:
    rgb = color.lab2rgb(np.asarray(lab_value, dtype=np.float64)[None, None, :])[0, 0]
    values = np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)
    return tuple(int(value) for value in values)
