from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np
from skimage import color

from .regions import build_adjacency


WEAK_SOURCE_DELTA_E = 2.0
WEAK_BOUNDARY_EVIDENCE = 0.20
HARD_BOUNDARY_EVIDENCE = 0.70


@dataclass(frozen=True)
class HierarchicalMergeResult:
    label_map: np.ndarray
    region_lab: dict[int, np.ndarray]
    protection_scores: dict[int, float]
    metrics: dict[str, object]


def compact_hierarchically(
    source_rgb: np.ndarray,
    region_map: np.ndarray,
    palette_lab: np.ndarray,
    protection_scores: dict[int, float],
    boundary_evidence: dict[tuple[int, int], float],
    target_region_count: int,
    maximum_region_count: int,
    user_protected_pairs: set[tuple[int, int]] | None = None,
    minimum_area_pixels: float = 0.0,
    minimum_width_pixels: float = 0.0,
) -> HierarchicalMergeResult:
    """Dynamically merge regions using immutable source-pixel palette costs."""
    maximum = int(region_map.max())
    source_lab = color.rgb2lab(source_rgb.astype(np.float64) / 255.0)
    flat_labels = region_map.ravel()
    area = np.bincount(flat_labels, minlength=maximum + 1).astype(np.float64)
    lab_sums = np.zeros((maximum + 1, 3), dtype=np.float64)
    for channel in range(3):
        lab_sums[:, channel] = np.bincount(
            flat_labels,
            weights=source_lab[..., channel].ravel(),
            minlength=maximum + 1,
        )
    palette_costs = np.zeros((maximum + 1, len(palette_lab)), dtype=np.float64)
    for color_index, paint_lab in enumerate(palette_lab):
        delta = color.deltaE_ciede2000(source_lab, paint_lab[None, None, :])
        palette_costs[:, color_index] = np.bincount(
            flat_labels,
            weights=delta.ravel(),
            minlength=maximum + 1,
        )

    adjacency = build_adjacency(region_map)
    shared = _shared_boundary_lengths(region_map)
    perimeter = np.zeros(maximum + 1, dtype=np.float64)
    for first, second in ((region_map[:, :-1], region_map[:, 1:]), (region_map[:-1, :], region_map[1:, :])):
        changed = first != second
        perimeter += np.bincount(first[changed], minlength=maximum + 1)
        perimeter += np.bincount(second[changed], minlength=maximum + 1)
    for border in (region_map[0], region_map[-1], region_map[:, 0], region_map[:, -1]):
        perimeter += np.bincount(border, minlength=maximum + 1)
    evidence = dict(boundary_evidence)
    user_edge = {pair: pair in set(user_protected_pairs or set()) for pair in shared}
    parent = np.arange(maximum + 1, dtype=np.int32)
    active = area > 0
    active[0] = False
    versions = np.zeros(maximum + 1, dtype=np.int32)
    region_protection = np.zeros(maximum + 1, dtype=np.float64)
    for region_id, value in protection_scores.items():
        if 0 < region_id <= maximum:
            region_protection[region_id] = value
    active_count = int(active.sum())
    weak_merges = 0
    density_merges = 0
    forced_user_merges = 0

    def mean_lab(region_id: int) -> np.ndarray:
        return lab_sums[region_id] / max(1.0, area[region_id])

    def below_print_floor(region_id: int) -> bool:
        return (
            area[region_id] < minimum_area_pixels
            or 2.0 * area[region_id] / max(1.0, perimeter[region_id]) < minimum_width_pixels
        )

    def edge_values(left: int, right: int) -> tuple[int, float, float, float, float, float, float]:
        pair = _pair(left, right)
        total_area = area[left] + area[right]
        reconstruction = (
            float(np.min(palette_costs[left] + palette_costs[right]))
            - float(np.min(palette_costs[left]))
            - float(np.min(palette_costs[right]))
        ) / max(1.0, total_area)
        boundary = float(evidence.get(pair, max(region_protection[left], region_protection[right])))
        delta = float(color.deltaE_ciede2000(mean_lab(left)[None, :], mean_lab(right)[None, :])[0])
        contact = shared.get(pair, 1) / max(1.0, np.sqrt(min(area[left], area[right])))
        shape = abs(area[left] - area[right]) / max(1.0, total_area)
        reconstruction = max(0.0, reconstruction)
        # Both terms are in approximate Delta-E units. A tiny eye therefore
        # competes on contrast and source-edge support, not on its pixel area.
        # The selected mask increases evidence without making an impenetrable
        # processing box; a physical or palette constraint can still win.
        edge_loss = boundary * delta * (2.0 if user_edge.get(pair, False) else 1.0)
        print_priority = 0 if below_print_floor(left) or below_print_floor(right) else 1
        return print_priority, reconstruction + edge_loss, reconstruction, boundary, delta, shape, contact

    def valid(left: int, right: int, left_version: int, right_version: int) -> bool:
        return (
            active[left]
            and active[right]
            and right in adjacency.get(left, set())
            and versions[left] == left_version
            and versions[right] == right_version
        )

    def merge(left: int, right: int) -> tuple[int, set[int], bool]:
        nonlocal active_count
        pair = _pair(left, right)
        selected = bool(user_edge.get(pair, False))
        shared_contact = shared.get(pair, 0)
        target, source = (left, right) if left < right else (right, left)
        parent[source] = target
        active[source] = False
        area[target] += area[source]
        lab_sums[target] += lab_sums[source]
        palette_costs[target] += palette_costs[source]
        perimeter[target] += perimeter[source] - 2.0 * shared_contact
        region_protection[target] = max(region_protection[target], region_protection[source])
        versions[target] += 1
        neighbours = (set(adjacency.get(target, set())) | set(adjacency.get(source, set()))) - {target, source}
        adjacency[target] = neighbours
        adjacency[source] = set()
        for neighbour in neighbours:
            adjacency[neighbour].discard(source)
            adjacency[neighbour].discard(target)
            adjacency[neighbour].add(target)
            target_pair = _pair(target, neighbour)
            source_pair = _pair(source, neighbour)
            target_length = shared.get(target_pair, 0)
            source_length = shared.get(source_pair, 0)
            total_length = target_length + source_length
            shared[target_pair] = total_length
            if total_length:
                evidence[target_pair] = (
                    evidence.get(target_pair, 0.0) * target_length
                    + evidence.get(source_pair, 0.0) * source_length
                ) / total_length
            user_edge[target_pair] = user_edge.get(target_pair, False) or user_edge.get(source_pair, False)
        active_count -= 1
        return target, neighbours, selected

    weak_heap: list[tuple[float, float, float, float, int, int, int, int]] = []

    def push_weak(left: int, right: int) -> None:
        if left == right or not active[left] or not active[right]:
            return
        left, right = _pair(left, right)
        _, _, reconstruction, boundary, delta, _, contact = edge_values(left, right)
        if delta < WEAK_SOURCE_DELTA_E and boundary < WEAK_BOUNDARY_EVIDENCE:
            heapq.heappush(
                weak_heap,
                (boundary, reconstruction, delta, -contact, left, right, int(versions[left]), int(versions[right])),
            )

    for left, neighbours in adjacency.items():
        for right in neighbours:
            if left < right:
                push_weak(left, right)
    while weak_heap:
        _, _, _, _, left, right, left_version, right_version = heapq.heappop(weak_heap)
        if not valid(left, right, left_version, right_version):
            continue
        target, neighbours, _ = merge(left, right)
        weak_merges += 1
        for neighbour in neighbours:
            push_weak(target, neighbour)

    density_heap: list[tuple[int, float, float, float, float, float, float, int, int, int, int]] = []
    physical_merges = 0

    def push_density(left: int, right: int) -> None:
        if left == right or not active[left] or not active[right]:
            return
        left, right = _pair(left, right)
        print_priority, cost, reconstruction, boundary, delta, shape, contact = edge_values(left, right)
        heapq.heappush(
            density_heap,
            (print_priority, cost, boundary, reconstruction, delta, shape, -contact, left, right, int(versions[left]), int(versions[right])),
        )

    for left, neighbours in adjacency.items():
        if not active[left]:
            continue
        for right in neighbours:
            if left < right:
                push_density(left, right)
    while density_heap:
        print_priority, _, _, _, _, _, _, left, right, left_version, right_version = heapq.heappop(density_heap)
        if not valid(left, right, left_version, right_version):
            continue
        if active_count <= target_region_count and print_priority != 0:
            break
        if user_edge.get(_pair(left, right), False) and active_count <= maximum_region_count and print_priority != 0:
            continue
        target, neighbours, selected = merge(left, right)
        density_merges += 1
        physical_merges += int(print_priority == 0)
        forced_user_merges += int(selected)
        for neighbour in neighbours:
            push_density(target, neighbour)

    if active_count > maximum_region_count:
        forced_heap: list[tuple[int, float, float, float, float, float, float, int, int, int, int]] = []
        for left, neighbours in adjacency.items():
            if not active[left]:
                continue
            for right in neighbours:
                if left >= right:
                    continue
                print_priority, cost, reconstruction, boundary, delta, shape, contact = edge_values(left, right)
                heapq.heappush(
                    forced_heap,
                    (print_priority, cost, boundary, reconstruction, delta, shape, -contact, left, right, int(versions[left]), int(versions[right])),
                )
        while forced_heap and active_count > maximum_region_count:
            _, _, _, _, _, _, _, left, right, left_version, right_version = heapq.heappop(forced_heap)
            if not valid(left, right, left_version, right_version):
                continue
            target, neighbours, selected = merge(left, right)
            density_merges += 1
            forced_user_merges += int(selected)
            for neighbour in neighbours:
                print_priority, cost, reconstruction, boundary, delta, shape, contact = edge_values(target, neighbour)
                a, b = _pair(target, neighbour)
                heapq.heappush(
                    forced_heap,
                    (print_priority, cost, boundary, reconstruction, delta, shape, -contact, a, b, int(versions[a]), int(versions[b])),
                )
    if active_count > maximum_region_count:
        raise ValueError("protected microregion graph could not be compacted within the 10% overflow limit")

    roots = np.arange(maximum + 1, dtype=np.int32)
    for region_id in range(1, maximum + 1):
        root = region_id
        while parent[root] != root:
            root = int(parent[root])
        roots[region_id] = root
    rooted = roots[region_map]
    active_roots = np.unique(rooted[rooted > 0])
    root_to_compact = {int(root): index + 1 for index, root in enumerate(active_roots)}
    lookup = np.zeros(maximum + 1, dtype=np.int32)
    for region_id in range(1, maximum + 1):
        if area[region_id] > 0 or parent[region_id] != region_id:
            lookup[region_id] = root_to_compact[int(roots[region_id])]
    compacted = lookup[region_map]
    merged_lab = {
        root_to_compact[int(root)]: mean_lab(int(root))
        for root in active_roots
    }
    merged_protection = {
        root_to_compact[int(root)]: float(region_protection[int(root)])
        for root in active_roots
    }
    overflow = max(0.0, 100.0 * (active_count - target_region_count) / max(1, target_region_count))
    return HierarchicalMergeResult(
        label_map=compacted,
        region_lab=merged_lab,
        protection_scores=merged_protection,
        metrics={
            "initial_region_count": maximum,
            "density_ceiling": int(target_region_count),
            "maximum_protected_region_count": int(maximum_region_count),
            "weak_boundary_merge_count": weak_merges,
            "density_merge_count": density_merges,
            "physical_constraint_merge_count": physical_merges,
            "selected_forced_merge_count": forced_user_merges,
            "post_compaction_region_count": active_count,
            "protection_overflow_percent": round(overflow, 6),
            "source_pixel_palette_costs": True,
            "dynamic_adjacency_updates": True,
        },
    )


def _shared_boundary_lengths(region_map: np.ndarray) -> dict[tuple[int, int], int]:
    result: dict[tuple[int, int], int] = {}
    for left, right in ((region_map[:, :-1], region_map[:, 1:]), (region_map[:-1, :], region_map[1:, :])):
        changed = (left != right) & (left > 0) & (right > 0)
        for first, second in zip(left[changed], right[changed], strict=False):
            pair = _pair(int(first), int(second))
            result[pair] = result.get(pair, 0) + 1
    return result


def _pair(left: int, right: int) -> tuple[int, int]:
    return (left, right) if left < right else (right, left)
