from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from skimage.measure import label, regionprops


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def load_palette(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_connectivity(connectivity: int) -> int:
    return 1 if int(connectivity) <= 1 else 2


def render_label_map_colors(
    label_map: np.ndarray,
    palette: list[dict[str, Any]],
) -> np.ndarray:
    h, w = label_map.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)

    palette_rgb = np.array(
        [p["rgb"] for p in palette],
        dtype=np.uint8,
    )

    for color_id in np.unique(label_map):
        color_id_int = int(color_id)

        if color_id_int < 0 or color_id_int >= len(palette_rgb):
            continue

        out[label_map == color_id_int] = palette_rgb[color_id_int]

    return out


def render_region_colors(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
    palette: list[dict[str, Any]],
) -> np.ndarray:
    h, w = region_map.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)

    palette_rgb = np.array(
        [p["rgb"] for p in palette],
        dtype=np.uint8,
    )

    for region_id, color_id in region_to_color.items():
        if color_id < 0 or color_id >= len(palette_rgb):
            continue

        out[region_map == region_id] = palette_rgb[color_id]

    return out


def render_region_ids(region_map: np.ndarray) -> np.ndarray:
    return (
        region_map.astype(np.float32)
        / max(int(region_map.max()), 1)
        * 255
    ).astype(np.uint8)


def get_neighbors(
    region_map: np.ndarray,
    region_id: int,
) -> list[int]:
    mask = region_map == region_id

    dilated = cv2.dilate(
        mask.astype(np.uint8),
        np.ones((3, 3), np.uint8),
        iterations=1,
    ).astype(bool)

    border = dilated & ~mask
    ids = np.unique(region_map[border])

    return [
        int(x)
        for x in ids
        if int(x) != 0 and int(x) != region_id
    ]


def choose_dominant_neighbor_label(
    label_map: np.ndarray,
    component_mask: np.ndarray,
    current_label: int,
    object_map: np.ndarray | None = None,
    same_object_only: bool = True,
) -> int | None:
    dilated = cv2.dilate(
        component_mask.astype(np.uint8),
        np.ones((3, 3), np.uint8),
        iterations=1,
    ).astype(bool)

    border = dilated & ~component_mask.astype(bool)

    if object_map is not None and same_object_only:
        object_values = object_map[component_mask]

        if len(object_values) > 0:
            values, counts = np.unique(object_values, return_counts=True)
            dominant_object_id = int(values[int(np.argmax(counts))])
            border &= object_map == dominant_object_id

    neighbor_labels = label_map[border]
    neighbor_labels = neighbor_labels[neighbor_labels != current_label]

    if len(neighbor_labels) == 0:
        return None

    values, counts = np.unique(neighbor_labels, return_counts=True)
    return int(values[int(np.argmax(counts))])


def cleanup_micro_label_islands(
    label_map: np.ndarray,
    min_island_area: int = 80,
    iterations: int = 4,
    connectivity: int = 1,
    object_map: np.ndarray | None = None,
    same_object_only: bool = True,
) -> tuple[np.ndarray, int, int]:
    """
    Removes tiny connected components from the categorical label map.

    Use strict connectivity=1 by default so diagonal-touching dots are treated as
    separate tiny islands. This helps remove small specks that visually survive
    after border cleanup.
    """
    if min_island_area <= 0 or iterations <= 0:
        return label_map.copy(), 0, 0

    connectivity = normalize_connectivity(connectivity)
    cleaned = label_map.copy()

    total_changed_components = 0
    total_changed_pixels = 0

    for _ in range(iterations):
        changed_this_iteration = 0
        labels = np.unique(cleaned)

        for color_id in labels:
            color_id_int = int(color_id)
            color_mask = cleaned == color_id_int

            labeled = label(
                color_mask,
                connectivity=connectivity,
            )

            for region in regionprops(labeled):
                area = int(region.area)

                if area >= min_island_area:
                    continue

                coords = region.coords

                component_mask = np.zeros(cleaned.shape, dtype=bool)
                component_mask[coords[:, 0], coords[:, 1]] = True

                target_label = choose_dominant_neighbor_label(
                    label_map=cleaned,
                    component_mask=component_mask,
                    current_label=color_id_int,
                    object_map=object_map,
                    same_object_only=same_object_only,
                )

                if target_label is None:
                    continue

                cleaned[coords[:, 0], coords[:, 1]] = target_label
                total_changed_components += 1
                total_changed_pixels += area
                changed_this_iteration += 1

        if changed_this_iteration == 0:
            break

    return (
        cleaned.astype(label_map.dtype, copy=False),
        total_changed_components,
        total_changed_pixels,
    )


def build_regions_from_color_ids(
    label_map: np.ndarray,
    connectivity: int = 2,
) -> tuple[np.ndarray, dict[int, int]]:
    connectivity = normalize_connectivity(connectivity)

    h, w = label_map.shape
    region_map = np.zeros((h, w), dtype=np.int32)
    region_to_color: dict[int, int] = {}

    current_region_id = 1

    for color_id in np.unique(label_map):
        color_mask = label_map == color_id

        labeled = label(
            color_mask,
            connectivity=connectivity,
        )

        for region in regionprops(labeled):
            coords = region.coords

            region_map[
                coords[:, 0],
                coords[:, 1],
            ] = current_region_id

            region_to_color[current_region_id] = int(color_id)
            current_region_id += 1

    return region_map, region_to_color


def compute_region_areas(region_map: np.ndarray) -> dict[int, int]:
    ids, counts = np.unique(region_map, return_counts=True)

    return {
        int(i): int(c)
        for i, c in zip(ids, counts)
        if int(i) != 0
    }


def merge_region(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
    source_id: int,
    target_id: int,
) -> None:
    region_map[region_map == source_id] = target_id

    if source_id in region_to_color:
        del region_to_color[source_id]


def best_neighbor_for_small_region(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
    region_id: int,
) -> int | None:
    neighbors = [
        n
        for n in get_neighbors(region_map, region_id)
        if n in region_to_color
    ]

    if not neighbors:
        return None

    source_color = region_to_color[region_id]
    source_mask = region_map == region_id

    dilated_source = cv2.dilate(
        source_mask.astype(np.uint8),
        np.ones((3, 3), np.uint8),
        iterations=1,
    ).astype(bool)

    scores: list[tuple[int, int]] = []

    for neighbor_id in neighbors:
        neighbor_mask = region_map == neighbor_id

        shared_border = int(
            np.logical_and(
                dilated_source,
                neighbor_mask,
            ).sum()
        )

        same_color_bonus = (
            10_000
            if region_to_color[neighbor_id] == source_color
            else 0
        )

        score = same_color_bonus + shared_border
        scores.append((score, neighbor_id))

    scores.sort(reverse=True)
    return scores[0][1]


def cleanup_small_regions(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
    min_area: int,
) -> tuple[np.ndarray, dict[int, int], int]:
    changed = True
    merge_count = 0

    while changed:
        changed = False
        areas = compute_region_areas(region_map)

        small_regions = [
            rid
            for rid, area in areas.items()
            if area < min_area and rid in region_to_color
        ]

        if not small_regions:
            break

        small_regions.sort(key=lambda rid: areas[rid])

        for rid in small_regions:
            if rid not in region_to_color:
                continue

            target = best_neighbor_for_small_region(
                region_map=region_map,
                region_to_color=region_to_color,
                region_id=rid,
            )

            if target is None:
                continue

            merge_region(
                region_map=region_map,
                region_to_color=region_to_color,
                source_id=rid,
                target_id=target,
            )

            merge_count += 1
            changed = True

    return region_map, region_to_color, merge_count


def detect_same_color_touching_conflicts(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
) -> list[tuple[int, int]]:
    conflicts: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    for region_id in list(region_to_color.keys()):
        neighbors = get_neighbors(region_map, region_id)

        for neighbor_id in neighbors:
            if neighbor_id not in region_to_color:
                continue

            a = int(region_id)
            b = int(neighbor_id)
            pair: tuple[int, int] = (a, b) if a < b else (b, a)

            if pair in seen:
                continue

            seen.add(pair)

            if region_to_color.get(region_id) == region_to_color.get(neighbor_id):
                conflicts.append(pair)

    return conflicts


def split_conflicting_same_color_neighbors(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
    palette_size: int,
) -> tuple[np.ndarray, dict[int, int], int]:
    conflicts = detect_same_color_touching_conflicts(
        region_map=region_map,
        region_to_color=region_to_color,
    )

    areas = compute_region_areas(region_map)
    changed = 0

    for a, b in conflicts:
        if a not in region_to_color or b not in region_to_color:
            continue

        if region_to_color[a] != region_to_color[b]:
            continue

        smaller = a if areas.get(a, 0) < areas.get(b, 0) else b
        old_color = region_to_color[smaller]

        neighbor_colors = {
            region_to_color[n]
            for n in get_neighbors(region_map, smaller)
            if n in region_to_color
        }

        candidate_colors = [
            old_color - 1,
            old_color + 1,
            old_color - 2,
            old_color + 2,
        ]

        candidate_colors = [
            c
            for c in candidate_colors
            if 0 <= c < palette_size
        ]

        selected_color = None

        for candidate in candidate_colors:
            if candidate not in neighbor_colors:
                selected_color = candidate
                break

        if selected_color is None and candidate_colors:
            selected_color = candidate_colors[0]

        if selected_color is None:
            continue

        region_to_color[smaller] = int(selected_color)
        changed += 1

    return region_map, region_to_color, changed


def build_region_metadata(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
) -> list[dict[str, Any]]:
    areas = compute_region_areas(region_map)
    data: list[dict[str, Any]] = []

    for region_id, color_id in region_to_color.items():
        data.append(
            {
                "region_id": int(region_id),
                "color_id_zero_based": int(color_id),
                "paint_number": int(color_id) + 1,
                "area": int(areas.get(region_id, 0)),
            }
        )

    data.sort(key=lambda x: int(x["region_id"]))
    return data


def save_region_metadata(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
    output_path: str,
) -> None:
    data = build_region_metadata(
        region_map=region_map,
        region_to_color=region_to_color,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_conflicts(
    conflicts: list[tuple[int, int]],
    output_path: str,
) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "region_a": int(a),
                    "region_b": int(b),
                }
                for a, b in conflicts
            ],
            f,
            indent=2,
        )


def run_step6_island_cleanup(
    label_map_path: str,
    palette_path: str,
    output_dir: str,
    object_map_path: str | None = None,
    micro_island_cleanup_enabled: bool = True,
    micro_island_min_area: int = 80,
    micro_island_iterations: int = 4,
    micro_island_connectivity: int = 1,
    micro_island_same_object_only: bool = True,
    min_region_area: int = 700,
    split_same_color_neighbors: bool = False,
    connectivity: int = 2,
) -> dict[str, Any]:
    """
    Step 6: micro-island cleanup and final region-map creation.

    Input should normally be:
        step5_border_cleanup/label_map_border_cleaned.npy

    Output is the final region map consumed by the new template step:
        step6_island_cleanup/region_map.npy
        step6_island_cleanup/regions.json
    """
    ensure_dir(output_dir)

    connectivity = normalize_connectivity(connectivity)
    micro_island_connectivity = normalize_connectivity(micro_island_connectivity)

    label_map = np.load(label_map_path)
    palette = load_palette(palette_path)

    h, w = label_map.shape

    object_map: np.ndarray | None = None

    if object_map_path:
        maybe_object_map = np.load(object_map_path)

        if maybe_object_map.shape == label_map.shape:
            object_map = maybe_object_map

    label_map_before_cleanup = label_map.copy()

    micro_island_cleanup_component_count = 0
    micro_island_cleanup_changed_pixels = 0

    if micro_island_cleanup_enabled:
        (
            label_map,
            micro_island_cleanup_component_count,
            micro_island_cleanup_changed_pixels,
        ) = cleanup_micro_label_islands(
            label_map=label_map,
            min_island_area=micro_island_min_area,
            iterations=micro_island_iterations,
            connectivity=micro_island_connectivity,
            object_map=object_map,
            same_object_only=micro_island_same_object_only,
        )

    label_map_after_cleanup = label_map.copy()

    region_map, region_to_color = build_regions_from_color_ids(
        label_map=label_map,
        connectivity=connectivity,
    )

    initial_region_count = len(region_to_color)

    region_map, region_to_color, small_region_merge_count = cleanup_small_regions(
        region_map=region_map,
        region_to_color=region_to_color,
        min_area=min_region_area,
    )

    after_cleanup_region_count = len(region_to_color)

    conflict_split_count = 0

    if split_same_color_neighbors:
        region_map, region_to_color, conflict_split_count = (
            split_conflicting_same_color_neighbors(
                region_map=region_map,
                region_to_color=region_to_color,
                palette_size=len(palette),
            )
        )

    conflicts = detect_same_color_touching_conflicts(
        region_map=region_map,
        region_to_color=region_to_color,
    )

    final_region_count = len(region_to_color)

    label_map_final_path = str(Path(output_dir) / "label_map_final.npy")
    region_map_path = str(Path(output_dir) / "region_map.npy")
    regions_json_path = str(Path(output_dir) / "regions.json")
    conflicts_path = str(Path(output_dir) / "same_color_conflicts.json")

    before_preview_path = str(Path(output_dir) / "step6_label_map_before_island_cleanup.png")
    after_preview_path = str(Path(output_dir) / "step6_label_map_after_island_cleanup.png")
    final_preview_path = str(Path(output_dir) / "step6_final_region_color_image.png")
    region_ids_path = str(Path(output_dir) / "step6_region_ids.png")
    result_path = str(Path(output_dir) / "step6_result.json")

    np.save(label_map_final_path, label_map_after_cleanup)
    np.save(region_map_path, region_map)

    save_region_metadata(
        region_map=region_map,
        region_to_color=region_to_color,
        output_path=regions_json_path,
    )

    save_conflicts(
        conflicts=conflicts,
        output_path=conflicts_path,
    )

    Image.fromarray(
        render_label_map_colors(
            label_map=label_map_before_cleanup,
            palette=palette,
        )
    ).save(before_preview_path)

    Image.fromarray(
        render_label_map_colors(
            label_map=label_map_after_cleanup,
            palette=palette,
        )
    ).save(after_preview_path)

    Image.fromarray(
        render_region_colors(
            region_map=region_map,
            region_to_color=region_to_color,
            palette=palette,
        )
    ).save(final_preview_path)

    cv2.imwrite(
        region_ids_path,
        render_region_ids(region_map),
    )

    result = {
        "step": 6,
        "image_width": int(w),
        "image_height": int(h),
        "initial_region_count": int(initial_region_count),
        "after_cleanup_region_count": int(after_cleanup_region_count),
        "final_region_count": int(final_region_count),
        "small_region_merge_count": int(small_region_merge_count),
        "same_color_conflict_count": int(len(conflicts)),
        "conflict_split_count": int(conflict_split_count),
        "micro_island_cleanup_component_count": int(micro_island_cleanup_component_count),
        "micro_island_cleanup_changed_pixels": int(micro_island_cleanup_changed_pixels),
        "params": {
            "micro_island_cleanup_enabled": bool(micro_island_cleanup_enabled),
            "micro_island_min_area": int(micro_island_min_area),
            "micro_island_iterations": int(micro_island_iterations),
            "micro_island_connectivity": int(micro_island_connectivity),
            "micro_island_same_object_only": bool(micro_island_same_object_only),
            "min_region_area": int(min_region_area),
            "split_same_color_neighbors": bool(split_same_color_neighbors),
            "connectivity": int(connectivity),
        },
        "outputs": {
            "label_map_final": label_map_final_path,
            "region_map": region_map_path,
            "regions": regions_json_path,
            "conflicts": conflicts_path,
            "before_preview": before_preview_path,
            "after_preview": after_preview_path,
            "preview": final_preview_path,
            "region_ids": region_ids_path,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result
