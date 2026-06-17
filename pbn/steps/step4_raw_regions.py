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


def run_step4_raw_regions(
    label_map_path: str,
    palette_path: str,
    output_dir: str,
    connectivity: int = 2,
) -> dict[str, Any]:
    """
    Step 4: create raw regions from the Step 3 palette label map.

    This step intentionally does NOT smooth borders and does NOT remove islands.
    It exists so you can keep a stable raw-region baseline and rerun later cleanup
    steps without rerunning palette generation.
    """
    ensure_dir(output_dir)

    connectivity = normalize_connectivity(connectivity)

    label_map = np.load(label_map_path)
    palette = load_palette(palette_path)

    h, w = label_map.shape

    region_map, region_to_color = build_regions_from_color_ids(
        label_map=label_map,
        connectivity=connectivity,
    )

    raw_region_count = len(region_to_color)

    label_map_raw_path = str(Path(output_dir) / "label_map_raw.npy")
    raw_region_map_path = str(Path(output_dir) / "raw_region_map.npy")
    raw_regions_json_path = str(Path(output_dir) / "raw_regions.json")

    raw_label_preview_path = str(Path(output_dir) / "step4_raw_label_map.png")
    raw_region_preview_path = str(Path(output_dir) / "step4_raw_region_color_image.png")
    raw_region_ids_path = str(Path(output_dir) / "step4_raw_region_ids.png")
    result_path = str(Path(output_dir) / "step4_result.json")

    np.save(label_map_raw_path, label_map)
    np.save(raw_region_map_path, region_map)

    save_region_metadata(
        region_map=region_map,
        region_to_color=region_to_color,
        output_path=raw_regions_json_path,
    )

    Image.fromarray(
        render_label_map_colors(
            label_map=label_map,
            palette=palette,
        )
    ).save(raw_label_preview_path)

    Image.fromarray(
        render_region_colors(
            region_map=region_map,
            region_to_color=region_to_color,
            palette=palette,
        )
    ).save(raw_region_preview_path)

    cv2.imwrite(
        raw_region_ids_path,
        render_region_ids(region_map),
    )

    result = {
        "step": 4,
        "image_width": int(w),
        "image_height": int(h),
        "raw_region_count": int(raw_region_count),
        "params": {
            "connectivity": int(connectivity),
        },
        "outputs": {
            "label_map_raw": label_map_raw_path,
            "raw_region_map": raw_region_map_path,
            "raw_regions": raw_regions_json_path,
            "raw_label_preview": raw_label_preview_path,
            "raw_region_preview": raw_region_preview_path,
            "raw_region_ids": raw_region_ids_path,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result
