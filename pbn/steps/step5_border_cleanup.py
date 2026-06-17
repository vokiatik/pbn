from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


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


def render_id_map(id_map: np.ndarray) -> np.ndarray:
    return (
        id_map.astype(np.float32)
        / max(int(id_map.max()), 1)
        * 255
    ).astype(np.uint8)


def compute_boundary_mask(
    map_array: np.ndarray,
    connectivity: int = 2,
) -> np.ndarray:
    connectivity = normalize_connectivity(connectivity)

    h, w = map_array.shape
    boundary = np.zeros((h, w), dtype=bool)

    diff = map_array[:-1, :] != map_array[1:, :]
    boundary[:-1, :] |= diff
    boundary[1:, :] |= diff

    diff = map_array[:, :-1] != map_array[:, 1:]
    boundary[:, :-1] |= diff
    boundary[:, 1:] |= diff

    if connectivity == 2:
        diff = map_array[:-1, :-1] != map_array[1:, 1:]
        boundary[:-1, :-1] |= diff
        boundary[1:, 1:] |= diff

        diff = map_array[:-1, 1:] != map_array[1:, :-1]
        boundary[:-1, 1:] |= diff
        boundary[1:, :-1] |= diff

    return boundary


def load_sam_metadata(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"SAM metadata should be a list: {path}")

    return data


def read_mask(path: str, expected_shape: tuple[int, int]) -> np.ndarray | None:
    mask = cv2.imread(path, cv2.IMREAD_GRAYSCALE)

    if mask is None:
        return None

    if mask.shape != expected_shape:
        mask = cv2.resize(
            mask,
            (expected_shape[1], expected_shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )

    return mask > 127


def build_object_map_from_sam_metadata(
    sam_metadata_path: str,
    shape: tuple[int, int],
) -> tuple[np.ndarray, int]:
    """
    Builds an object_id map from Step 1 SAM metadata.

    Object id 0 means background/no object. Larger/smaller masks can overlap, so
    we replay masks from large to small, letting smaller masks overwrite bigger
    masks, similar to Step 1 label visualization behavior.
    """
    metadata = load_sam_metadata(sam_metadata_path)

    object_map = np.zeros(shape, dtype=np.int32)

    sorted_items = sorted(
        metadata,
        key=lambda item: int(item.get("area", 0)),
        reverse=True,
    )

    loaded_count = 0

    for item in sorted_items:
        object_id = int(item.get("id", loaded_count + 1))
        mask_path = item.get("mask_path")

        if not mask_path:
            continue

        mask = read_mask(str(mask_path), expected_shape=shape)

        if mask is None:
            continue

        object_map[mask] = object_id
        loaded_count += 1

    return object_map, loaded_count


def build_cleanup_allowed_mask(
    object_map: np.ndarray,
    object_boundary_guard_px: int,
    cleanup_background: bool,
    boundary_cleanup_radius: int,
) -> np.ndarray:
    """
    Allows cleanup only away from SAM object boundaries.

    If cleanup_background is false, cleanup is allowed only inside object interiors.
    If true, it is allowed in object interiors and background interiors, but still
    avoids the protected object-boundary guard band.
    """
    object_boundary = compute_boundary_mask(
        object_map,
        connectivity=2,
    )

    effective_guard_px = max(
        int(object_boundary_guard_px),
        int(boundary_cleanup_radius),
        0,
    )

    if effective_guard_px > 0:
        kernel_size = effective_guard_px * 2 + 1
        guard = cv2.dilate(
            object_boundary.astype(np.uint8),
            np.ones((kernel_size, kernel_size), np.uint8),
            iterations=1,
        ).astype(bool)
    else:
        guard = object_boundary

    allowed = ~guard

    if not cleanup_background:
        allowed &= object_map != 0

    return allowed


def cleanup_boundary_artifacts(
    label_map: np.ndarray,
    radius: int = 2,
    iterations: int = 2,
    dominance_threshold: float = 0.60,
    min_advantage: int = 3,
    max_current_support_ratio: float = 0.35,
    connectivity: int = 2,
    allowed_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, int]:
    """
    Selective boundary cleanup / de-zippering.

    This is not global smoothing. It only edits boundary pixels, and with
    object-guided cleanup enabled, only pixels inside safe SAM object/background
    interiors are candidates.
    """
    if radius <= 0 or iterations <= 0:
        return label_map.copy(), 0

    connectivity = normalize_connectivity(connectivity)

    current = label_map.copy()

    kernel_size = radius * 2 + 1
    window_area = float(kernel_size * kernel_size)

    total_changed_pixels = 0

    if allowed_mask is None:
        allowed_mask = np.ones(current.shape, dtype=bool)
    else:
        allowed_mask = allowed_mask.astype(bool)

    for _ in range(iterations):
        labels = np.unique(current)

        boundary_mask = compute_boundary_mask(
            current,
            connectivity=connectivity,
        )

        boundary_mask &= allowed_mask

        if not boundary_mask.any():
            break

        best_label = current.copy()
        best_count = np.full(current.shape, -1.0, dtype=np.float32)
        current_count = np.zeros(current.shape, dtype=np.float32)

        for color_id in labels:
            mask = (current == color_id).astype(np.uint8)

            counts = cv2.boxFilter(
                mask,
                ddepth=cv2.CV_32F,
                ksize=(kernel_size, kernel_size),
                normalize=False,
                borderType=cv2.BORDER_REPLICATE,
            )

            own_pixels = current == color_id
            current_count[own_pixels] = counts[own_pixels]

            better = counts > best_count
            best_count[better] = counts[better]
            best_label[better] = color_id

        dominance_ratio = best_count / window_area
        current_support_ratio = current_count / window_area
        advantage = best_count - current_count

        should_change = (
            boundary_mask
            & (best_label != current)
            & (dominance_ratio >= float(dominance_threshold))
            & (advantage >= float(min_advantage))
            & (current_support_ratio <= float(max_current_support_ratio))
        )

        changed_pixels = int(should_change.sum())

        if changed_pixels == 0:
            break

        current[should_change] = best_label[should_change]
        total_changed_pixels += changed_pixels

    return current.astype(label_map.dtype, copy=False), total_changed_pixels


def run_step5_border_cleanup(
    label_map_path: str,
    palette_path: str,
    output_dir: str,
    sam_metadata_path: str | None = None,
    cleanup_boundary_artifacts_enabled: bool = True,
    boundary_cleanup_radius: int = 3,
    boundary_cleanup_iterations: int = 3,
    boundary_dominance_threshold: float = 0.58,
    boundary_min_advantage: int = 2,
    boundary_max_current_support_ratio: float = 0.45,
    use_object_guided_cleanup: bool = True,
    object_boundary_guard_px: int = 4,
    cleanup_background: bool = True,
    connectivity: int = 2,
) -> dict[str, Any]:
    """
    Step 5: object-guided border cleanup / de-zippering.

    Input should normally be:
        step4_raw_regions/label_map_raw.npy

    Output is:
        step5_border_cleanup/label_map_border_cleaned.npy

    You can rerun this step with different smoothing/de-zippering params without
    rerunning Step 4 raw region creation.
    """
    ensure_dir(output_dir)

    connectivity = normalize_connectivity(connectivity)

    label_map = np.load(label_map_path)
    palette = load_palette(palette_path)

    h, w = label_map.shape

    object_map = np.zeros((h, w), dtype=np.int32)
    loaded_object_mask_count = 0
    allowed_mask = np.ones((h, w), dtype=bool)

    if use_object_guided_cleanup:
        if sam_metadata_path is None:
            raise ValueError(
                "sam_metadata_path is required when use_object_guided_cleanup=True"
            )

        object_map, loaded_object_mask_count = build_object_map_from_sam_metadata(
            sam_metadata_path=sam_metadata_path,
            shape=(h, w),
        )

        allowed_mask = build_cleanup_allowed_mask(
            object_map=object_map,
            object_boundary_guard_px=object_boundary_guard_px,
            cleanup_background=cleanup_background,
            boundary_cleanup_radius=boundary_cleanup_radius,
        )

    label_map_before_cleanup = label_map.copy()
    boundary_cleanup_changed_pixels = 0

    if cleanup_boundary_artifacts_enabled:
        label_map, boundary_cleanup_changed_pixels = cleanup_boundary_artifacts(
            label_map=label_map,
            radius=boundary_cleanup_radius,
            iterations=boundary_cleanup_iterations,
            dominance_threshold=boundary_dominance_threshold,
            min_advantage=boundary_min_advantage,
            max_current_support_ratio=boundary_max_current_support_ratio,
            connectivity=connectivity,
            allowed_mask=allowed_mask,
        )

    label_map_after_cleanup = label_map.copy()

    label_map_border_cleaned_path = str(Path(output_dir) / "label_map_border_cleaned.npy")
    before_preview_path = str(Path(output_dir) / "step5_label_map_before_border_cleanup.png")
    after_preview_path = str(Path(output_dir) / "step5_label_map_after_border_cleanup.png")
    border_cleaned_preview_path = str(Path(output_dir) / "step5_border_cleaned_preview.png")
    object_map_path = str(Path(output_dir) / "object_map.npy")
    object_map_preview_path = str(Path(output_dir) / "step5_object_map.png")
    safe_cleanup_mask_path = str(Path(output_dir) / "safe_cleanup_mask.png")
    result_path = str(Path(output_dir) / "step5_result.json")

    np.save(label_map_border_cleaned_path, label_map_after_cleanup)
    np.save(object_map_path, object_map)

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
        render_label_map_colors(
            label_map=label_map_after_cleanup,
            palette=palette,
        )
    ).save(border_cleaned_preview_path)

    cv2.imwrite(object_map_preview_path, render_id_map(object_map))
    cv2.imwrite(safe_cleanup_mask_path, allowed_mask.astype(np.uint8) * 255)

    result = {
        "step": 5,
        "image_width": int(w),
        "image_height": int(h),
        "boundary_cleanup_changed_pixels": int(boundary_cleanup_changed_pixels),
        "loaded_object_mask_count": int(loaded_object_mask_count),
        "params": {
            "cleanup_boundary_artifacts_enabled": bool(cleanup_boundary_artifacts_enabled),
            "boundary_cleanup_radius": int(boundary_cleanup_radius),
            "boundary_cleanup_iterations": int(boundary_cleanup_iterations),
            "boundary_dominance_threshold": float(boundary_dominance_threshold),
            "boundary_min_advantage": int(boundary_min_advantage),
            "boundary_max_current_support_ratio": float(boundary_max_current_support_ratio),
            "use_object_guided_cleanup": bool(use_object_guided_cleanup),
            "object_boundary_guard_px": int(object_boundary_guard_px),
            "cleanup_background": bool(cleanup_background),
            "connectivity": int(connectivity),
        },
        "outputs": {
            "label_map_border_cleaned": label_map_border_cleaned_path,
            "before_preview": before_preview_path,
            "after_preview": after_preview_path,
            "preview": border_cleaned_preview_path,
            "object_map": object_map_path,
            "object_map_preview": object_map_preview_path,
            "safe_cleanup_mask": safe_cleanup_mask_path,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result
