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


def build_regions_from_color_ids(
    label_map: np.ndarray,
) -> tuple[np.ndarray, dict[int, int]]:
    h, w = label_map.shape

    region_map = np.zeros((h, w), dtype=np.int32)

    region_to_color: dict[int, int] = {}

    current_region_id = 1

    for color_id in np.unique(label_map):
        color_mask = label_map == color_id

        labeled = label(
            color_mask,
            connectivity=1,
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


def compute_region_areas(
    region_map: np.ndarray,
) -> dict[int, int]:
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
    neighbors = get_neighbors(region_map, region_id)

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
            pair = tuple[int, int](sorted((region_id, neighbor_id)))

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

        if not candidate_colors:
            continue

        region_to_color[smaller] = int(candidate_colors[0])

        changed += 1

    return region_map, region_to_color, changed


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


def render_region_ids(
    region_map: np.ndarray,
) -> np.ndarray:
    return (
        region_map.astype(np.float32)
        / max(int(region_map.max()), 1)
        * 255
    ).astype(np.uint8)


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


def run_step4_regions_cleanup(
    label_map_path: str,
    palette_path: str,
    output_dir: str,
    min_region_area: int = 250,
    split_same_color_neighbors: bool = False,
) -> dict[str, Any]:
    ensure_dir(output_dir)

    label_map = np.load(label_map_path)

    palette = load_palette(palette_path)

    h, w = label_map.shape

    region_map, region_to_color = build_regions_from_color_ids(label_map)

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

    final_color_img = render_region_colors(
        region_map=region_map,
        region_to_color=region_to_color,
        palette=palette,
    )

    conflicts = detect_same_color_touching_conflicts(
        region_map=region_map,
        region_to_color=region_to_color,
    )

    final_region_count = len(region_to_color)

    preview_path = str(Path(output_dir) / "step4_region_color_image.png")
    region_ids_path = str(Path(output_dir) / "step4_region_ids.png")
    region_map_path = str(Path(output_dir) / "region_map.npy")
    regions_json_path = str(Path(output_dir) / "regions.json")
    conflicts_path = str(Path(output_dir) / "same_color_conflicts.json")
    result_path = str(Path(output_dir) / "step4_result.json")

    Image.fromarray(final_color_img).save(preview_path)

    cv2.imwrite(
        region_ids_path,
        render_region_ids(region_map),
    )

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

    result = {
        "step": 4,
        "image_width": int(w),
        "image_height": int(h),
        "initial_region_count": int(initial_region_count),
        "after_cleanup_region_count": int(after_cleanup_region_count),
        "final_region_count": int(final_region_count),
        "small_region_merge_count": int(small_region_merge_count),
        "same_color_conflict_count": int(len(conflicts)),
        "conflict_split_count": int(conflict_split_count),
        "params": {
            "min_region_area": int(min_region_area),
            "split_same_color_neighbors": bool(split_same_color_neighbors),
        },
        "outputs": {
            "preview": preview_path,
            "region_ids": region_ids_path,
            "region_map": region_map_path,
            "regions": regions_json_path,
            "conflicts": conflicts_path,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result