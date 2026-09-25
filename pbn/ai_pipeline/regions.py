from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.measure import label as label_connected_components

from .io_utils import atomic_write_json, save_label_map_png
from .models import RegionRecord


FOUR_CONNECTED = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)


def extract_regions(
    illustration_path: Path,
    output_dir: Path,
    color_bin_size: int = 1,
    min_region_area: int = 1,
    max_region_count: int | None = None,
) -> tuple[np.ndarray, list[RegionRecord]]:
    with Image.open(illustration_path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)

    quantized = _quantize_rgb(rgb, color_bin_size)
    packed = (
        quantized[..., 0].astype(np.uint32) << 16
        | quantized[..., 1].astype(np.uint32) << 8
        | quantized[..., 2].astype(np.uint32)
    )
    label_map = label_connected_components(
        packed.astype(np.int64),
        connectivity=1,
        background=-1,
    ).astype(np.int32)
    label_map = _absorb_small_regions(label_map, min_region_area)

    region_count = int(np.unique(label_map[label_map > 0]).size)
    if max_region_count is not None and region_count > max_region_count:
        raise ValueError(
            f"AI image is too detailed for paint-by-number tracing: {region_count} regions "
            f"after simplification, limit is {max_region_count}. Try simplifying more "
            "background or texture details."
        )

    adjacency = build_adjacency(label_map)
    records = build_region_records(label_map, rgb, adjacency)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "region_id_map.npy", label_map)
    save_label_map_png(label_map, output_dir / "initial_region_map.png")
    atomic_write_json(output_dir / "regions.json", [record_to_dict(record) for record in records])
    atomic_write_json(
        output_dir / "adjacency.json",
        {str(region_id): sorted(neighbours) for region_id, neighbours in adjacency.items()},
    )
    return label_map, records


def build_adjacency(label_map: np.ndarray) -> dict[int, set[int]]:
    adjacency: dict[int, set[int]] = defaultdict(set)
    for shifted_a, shifted_b in (
        (label_map[:, :-1], label_map[:, 1:]),
        (label_map[:-1, :], label_map[1:, :]),
    ):
        mask = shifted_a != shifted_b
        for left, right in zip(shifted_a[mask].ravel(), shifted_b[mask].ravel(), strict=False):
            if left == 0 or right == 0:
                continue
            adjacency[int(left)].add(int(right))
            adjacency[int(right)].add(int(left))
    for region_id in np.unique(label_map):
        if region_id:
            adjacency.setdefault(int(region_id), set())
    return adjacency


def build_region_records(
    label_map: np.ndarray,
    rgb: np.ndarray,
    adjacency: dict[int, set[int]],
    color_ids: dict[int, int] | None = None,
) -> list[RegionRecord]:
    records: list[RegionRecord] = []
    objects = ndimage.find_objects(label_map)
    for region_id, region_slice in enumerate(objects, start=1):
        if region_slice is None:
            continue
        top, bottom = int(region_slice[0].start or 0), int(region_slice[0].stop or label_map.shape[0])
        left, right = int(region_slice[1].start or 0), int(region_slice[1].stop or label_map.shape[1])
        mask = label_map[region_slice] == region_id
        area = int(mask.sum())
        perimeter = _perimeter(mask)
        representative = tuple(int(round(v)) for v in np.median(rgb[region_slice][mask], axis=0))
        records.append(
            RegionRecord(
                region_id=region_id,
                color_id=(color_ids or {}).get(region_id, 0),
                area=area,
                bbox=(left, top, right, bottom),
                perimeter=perimeter,
                estimated_thickness=2.0 * area / max(perimeter, 1),
                representative_color=representative,
                neighbours=sorted(adjacency.get(region_id, set())),
                holes=_hole_count(mask),
                components=int(ndimage.label(mask, structure=FOUR_CONNECTED)[1]),
            )
        )
    return records


def record_to_dict(record: RegionRecord) -> dict[str, object]:
    return {
        "region_id": record.region_id,
        "color_id": record.color_id,
        "area": record.area,
        "bbox": list(record.bbox),
        "perimeter": record.perimeter,
        "estimated_thickness": record.estimated_thickness,
        "representative_source_colour": list(record.representative_color),
        "neighbouring_regions": record.neighbours,
        "holes": record.holes,
        "internal_components": record.components,
    }


def _quantize_rgb(rgb: np.ndarray, bin_size: int) -> np.ndarray:
    bins = max(1, int(bin_size))
    return np.clip(((rgb.astype(np.int16) + bins // 2) // bins) * bins, 0, 255).astype(np.uint8)


def _absorb_small_regions(label_map: np.ndarray, min_area: int) -> np.ndarray:
    min_size = max(1, int(min_area))
    if min_size <= 1:
        return label_map

    sizes = np.bincount(label_map.ravel())
    small_ids = np.flatnonzero((sizes > 0) & (sizes < min_size))
    if len(small_ids) == 0:
        return label_map

    small_mask = np.isin(label_map, small_ids)
    if not small_mask.any() or small_mask.all():
        return label_map

    cleaned = label_map.copy()
    cleaned[small_mask] = 0
    nearest = ndimage.distance_transform_edt(
        cleaned == 0,
        return_distances=False,
        return_indices=True,
    )
    cleaned[small_mask] = cleaned[tuple(axis[small_mask] for axis in nearest)]
    return _compact_labels(cleaned)


def _compact_labels(label_map: np.ndarray) -> np.ndarray:
    labels = np.unique(label_map)
    labels = labels[labels > 0]
    if len(labels) == 0:
        return label_map
    remap = np.zeros(int(labels.max()) + 1, dtype=np.int32)
    remap[labels] = np.arange(1, len(labels) + 1, dtype=np.int32)
    return remap[label_map]


def _perimeter(mask: np.ndarray) -> int:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    center = padded[1:-1, 1:-1]
    exposed = (
        (center & ~padded[1:-1, :-2]).sum()
        + (center & ~padded[1:-1, 2:]).sum()
        + (center & ~padded[:-2, 1:-1]).sum()
        + (center & ~padded[2:, 1:-1]).sum()
    )
    return int(exposed)


def _hole_count(mask: np.ndarray) -> int:
    filled = ndimage.binary_fill_holes(mask)
    holes = filled & ~mask
    if not holes.any():
        return 0
    _, count = ndimage.label(holes, structure=FOUR_CONNECTED)
    return int(count)
