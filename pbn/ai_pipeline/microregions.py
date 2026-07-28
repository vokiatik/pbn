from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage import color
from skimage.measure import label as label_connected_components

from .regions import build_adjacency, build_region_records
from .segmentation import region_boundary_evidence


MICROREGION_LIMIT = 100_000
COLLAPSE_PASSES = ((0.5, 0.05), (1.0, 0.10), (2.0, 0.20))


@dataclass(frozen=True)
class MicroregionResult:
    label_map: np.ndarray
    metrics: dict[str, object]


def build_source_microregions(
    source_rgb: np.ndarray,
    zone: np.ndarray,
    maximum_regions: int = MICROREGION_LIMIT,
) -> MicroregionResult:
    packed = (
        source_rgb[..., 0].astype(np.int64) << 16
        | source_rgb[..., 1].astype(np.int64) << 8
        | source_rgb[..., 2].astype(np.int64)
    )
    values = packed.copy()
    values[~zone] = -1
    labels = label_connected_components(values, connectivity=1, background=-1).astype(np.int32)
    initial_count = _region_count(labels)
    pass_reports: list[dict[str, object]] = []
    for index, (maximum_delta, maximum_evidence) in enumerate(COLLAPSE_PASSES):
        labels, merged = _collapse_unsupported(
            source_rgb,
            labels,
            maximum_delta=maximum_delta,
            maximum_evidence=maximum_evidence,
        )
        count = _region_count(labels)
        pass_reports.append(
            {
                "pass": index + 1,
                "maximum_delta_e_00": maximum_delta,
                "maximum_boundary_evidence": maximum_evidence,
                "merge_count": merged,
                "region_count": count,
            }
        )
        if index == 0 and count <= maximum_regions:
            break
        if count <= maximum_regions:
            break
    final_count = _region_count(labels)
    if final_count > maximum_regions:
        raise ValueError(
            f"selected detail contains {final_count} source microregions after safe collapse; "
            f"limit is {maximum_regions}. Reduce the protected area or simplify the reviewed image."
        )
    return MicroregionResult(
        label_map=labels,
        metrics={
            "initial_exact_component_count": initial_count,
            "final_microregion_count": final_count,
            "microregion_limit": maximum_regions,
            "collapse_passes": pass_reports,
        },
    )


def _collapse_unsupported(
    source_rgb: np.ndarray,
    label_map: np.ndarray,
    maximum_delta: float,
    maximum_evidence: float,
) -> tuple[np.ndarray, int]:
    region_ids = [int(value) for value in np.unique(label_map) if int(value)]
    if len(region_ids) <= 1:
        return label_map, 0
    records = build_region_records(label_map, source_rgb, build_adjacency(label_map))
    rgb = np.asarray([record.representative_color for record in records], dtype=np.uint8)
    labs = color.rgb2lab(rgb[:, None, :].astype(np.float64) / 255.0)[:, 0, :]
    lab_by_id = {record.region_id: labs[index] for index, record in enumerate(records)}
    evidence = region_boundary_evidence(source_rgb, label_map)
    pairs: list[tuple[int, int]] = []
    for pair in sorted(evidence):
        delta = float(color.deltaE_ciede2000(lab_by_id[pair[0]][None, :], lab_by_id[pair[1]][None, :])[0])
        # The general evidence score intentionally includes topology and contact.
        # Initial exact-colour cleanup needs source-only support so a flat two-node
        # graph is not protected merely because both nodes have low degree.
        source_only_evidence = min(float(evidence[pair]), min(1.0, delta / 10.0))
        if delta < maximum_delta and source_only_evidence < maximum_evidence:
            pairs.append(pair)
    if not pairs:
        return label_map, 0
    maximum = int(label_map.max())
    parent = np.arange(maximum + 1, dtype=np.int32)

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[int(parent[value])]
            value = int(parent[value])
        return value

    merges = 0
    for left, right in pairs:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            continue
        target, source = (left_root, right_root) if left_root < right_root else (right_root, left_root)
        parent[source] = target
        merges += 1
    roots = np.arange(maximum + 1, dtype=np.int32)
    for region_id in region_ids:
        roots[region_id] = find(region_id)
    return _compact_labels(roots[label_map]), merges


def _compact_labels(label_map: np.ndarray) -> np.ndarray:
    values = np.unique(label_map)
    values = values[values > 0]
    if len(values) == 0:
        return label_map.astype(np.int32)
    lookup = np.zeros(int(values.max()) + 1, dtype=np.int32)
    lookup[values] = np.arange(1, len(values) + 1, dtype=np.int32)
    return lookup[label_map]


def _region_count(label_map: np.ndarray) -> int:
    return int(np.unique(label_map[label_map > 0]).size)
