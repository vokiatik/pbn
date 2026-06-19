import os
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from sklearn.cluster import MiniBatchKMeans
import pillow_heif

pillow_heif.register_heif_opener()

def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def read_rgb(path: str) -> np.ndarray:
    suffix = Path(path).suffix.lower()

    if suffix in {".heic", ".heif"}:
        try:
            img = Image.open(path)
            img = img.convert("RGB")
            return np.array(img, dtype=np.uint8)
        except Exception as e:
            raise FileNotFoundError(f"Could not read HEIC/HEIF image: {path}") from e

    bgr = cv2.imread(path, cv2.IMREAD_COLOR)

    if bgr is None:
        raise FileNotFoundError(f"Could not read image: {path}")

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def read_mask(path: str) -> np.ndarray:
    mask = cv2.imread(path, cv2.IMREAD_GRAYSCALE)

    if mask is None:
        raise FileNotFoundError(f"Could not read mask: {path}")

    return mask > 127


def dominant_colors_lab(
    rgb_pixels: np.ndarray,
    k: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(rgb_pixels) == 0:
        raise ValueError("dominant_colors_lab received empty pixel array")

    lab = cv2.cvtColor(
        rgb_pixels.reshape(-1, 1, 3),
        cv2.COLOR_RGB2LAB,
    )

    lab = lab.reshape(-1, 3).astype(np.float32)

    k = max(1, min(k, len(lab)))

    kmeans = MiniBatchKMeans(
        n_clusters=k,
        random_state=42,
        batch_size=4096,
        n_init="auto",
    )

    labels = kmeans.fit_predict(lab).astype(np.int32)

    centers_lab = kmeans.cluster_centers_.astype(np.uint8)

    centers_rgb = cv2.cvtColor(
        centers_lab.reshape(-1, 1, 3),
        cv2.COLOR_LAB2RGB,
    ).reshape(-1, 3)

    return labels, centers_rgb.astype(np.uint8)


def mean_lab_delta(
    lab: np.ndarray,
    component_mask: np.ndarray,
    ring_mask: np.ndarray,
) -> float:
    if not component_mask.any() or not ring_mask.any():
        return 0.0

    component_mean = lab[component_mask].mean(axis=0)
    ring_mean = lab[ring_mask].mean(axis=0)

    return float(np.linalg.norm(component_mean - ring_mean))


def build_detail_context(image_rgb: np.ndarray) -> dict[str, np.ndarray]:
    lab = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2LAB)
    blurred_lab = cv2.GaussianBlur(
        lab,
        ksize=(0, 0),
        sigmaX=3.0,
        sigmaY=3.0,
    )

    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    laplacian = cv2.convertScaleAbs(
        cv2.Laplacian(gray, cv2.CV_16S, ksize=3)
    )
    lab_diff = cv2.absdiff(lab, blurred_lab)

    return {
        "lab": lab,
        "lab_delta": (
            lab_diff[:, :, 0].astype(np.uint16)
            + lab_diff[:, :, 1].astype(np.uint16)
            + lab_diff[:, :, 2].astype(np.uint16)
        ),
        "laplacian": laplacian,
    }


def mask_bbox(mask: np.ndarray, padding: int = 0) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)

    if len(xs) == 0 or len(ys) == 0:
        return None

    y1 = max(int(ys.min()) - padding, 0)
    x1 = max(int(xs.min()) - padding, 0)
    y2 = min(int(ys.max()) + padding + 1, mask.shape[0])
    x2 = min(int(xs.max()) + padding + 1, mask.shape[1])

    return y1, x1, y2, x2


def detect_internal_detail_mask(
    image_rgb: np.ndarray,
    mask: np.ndarray,
    min_region_area: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Finds small high-contrast details inside a SAM object mask.

    SAM often gives a single large face/body mask without separate masks for
    eyes, lips, fingers, or accessories. Those pixels should not compete with
    the whole large object during local color smoothing.
    """
    mask_pixels = int(mask.sum())
    detail_mask = np.zeros(mask.shape, dtype=bool)

    if mask_pixels < max(int(min_region_area) * 2, 600):
        return detail_mask, {
            "enabled": True,
            "skipped": True,
            "reason": "mask too small",
            "component_count": 0,
            "pixels": 0,
        }

    bbox = mask_bbox(mask, padding=6)

    if bbox is None:
        return detail_mask, {
            "enabled": True,
            "skipped": True,
            "reason": "empty mask",
            "component_count": 0,
            "pixels": 0,
        }

    y1, x1, y2, x2 = bbox
    image_crop = image_rgb[y1:y2, x1:x2]
    mask_crop = mask[y1:y2, x1:x2]

    detail_context = build_detail_context(image_crop)
    lab = detail_context["lab"]
    lab_delta = detail_context["lab_delta"]
    laplacian = detail_context["laplacian"]

    kernel = np.ones((3, 3), np.uint8)
    inner_mask = cv2.erode(
        mask_crop.astype(np.uint8),
        kernel,
        iterations=2,
    ).astype(bool)

    if int(inner_mask.sum()) < int(min_region_area):
        inner_mask = mask_crop

    inner_delta = lab_delta[inner_mask]
    inner_laplacian = laplacian[inner_mask]

    if len(inner_delta) == 0:
        return detail_mask, {
            "enabled": True,
            "skipped": True,
            "reason": "empty inner mask",
            "component_count": 0,
            "pixels": 0,
        }

    delta_threshold = max(18.0, float(np.percentile(inner_delta, 92)))
    edge_threshold = max(20.0, float(np.percentile(inner_laplacian, 90)))

    candidates = (
        inner_mask
        & (
            (lab_delta >= delta_threshold)
            | (
                (laplacian >= edge_threshold)
                & (lab_delta >= 12.0)
            )
        )
    )

    component_count, component_map, stats, _ = cv2.connectedComponentsWithStats(
        candidates.astype(np.uint8),
        connectivity=8,
    )

    min_detail_area = max(6, int(min_region_area) // 50)
    max_detail_area = max(
        int(min_region_area),
        min(int(mask_pixels * 0.04), int(min_region_area) * 20),
    )
    max_detail_pixels = max(max_detail_area, int(mask_pixels * 0.08))

    components: list[dict[str, Any]] = []

    for component_id in range(1, component_count):
        area = int(stats[component_id, cv2.CC_STAT_AREA])

        if area < min_detail_area or area > max_detail_area:
            continue

        component_mask = component_map == component_id

        dilated = cv2.dilate(
            component_mask.astype(np.uint8),
            kernel,
            iterations=3,
        ).astype(bool)

        ring_mask = dilated & mask_crop & ~component_mask
        contrast = mean_lab_delta(
            lab=lab,
            component_mask=component_mask,
            ring_mask=ring_mask,
        )

        if contrast < 14.0:
            continue

        protected_component = cv2.dilate(
            component_mask.astype(np.uint8),
            kernel,
            iterations=1,
        ).astype(bool) & mask_crop

        components.append(
            {
                "component_id": int(component_id),
                "area": area,
                "protected_pixels": int(protected_component.sum()),
                "contrast_lab": contrast,
            }
        )

    components.sort(
        key=lambda item: (
            float(item["contrast_lab"]),
            int(item["area"]),
        ),
        reverse=True,
    )

    protected_count = 0
    kept_components = 0
    detail_crop = np.zeros(mask_crop.shape, dtype=bool)

    for component in components:
        component_mask = component_map == int(component["component_id"])
        protected_component = cv2.dilate(
            component_mask.astype(np.uint8),
            kernel,
            iterations=1,
        ).astype(bool) & mask_crop

        new_pixels = protected_component & ~detail_crop
        next_count = protected_count + int(new_pixels.sum())

        if next_count > max_detail_pixels:
            continue

        detail_crop |= protected_component
        protected_count = next_count
        kept_components += 1

    detail_mask[y1:y2, x1:x2] = detail_crop

    return detail_mask, {
        "enabled": True,
        "skipped": False,
        "component_count": int(kept_components),
        "candidate_component_count": int(len(components)),
        "pixels": int(detail_mask.sum()),
        "pixel_ratio": float(detail_mask.sum() / max(mask_pixels, 1)),
        "delta_threshold": float(delta_threshold),
        "edge_threshold": float(edge_threshold),
        "min_detail_area": int(min_detail_area),
        "max_detail_area": int(max_detail_area),
        "max_detail_pixels": int(max_detail_pixels),
    }


def color_component_stats(
    local_label_map: np.ndarray,
    mask: np.ndarray,
    min_area: int,
) -> dict[str, Any]:
    total_components = 0
    small_components = 0
    small_component_pixels = 0
    unassigned_pixels = int(((local_label_map == -1) & mask).sum())
    labels: list[dict[str, Any]] = []

    for color_id in sorted(int(x) for x in np.unique(local_label_map[mask]) if int(x) >= 0):
        color_region = ((local_label_map == color_id) & mask).astype(np.uint8)

        component_count, _, stats, _ = cv2.connectedComponentsWithStats(
            color_region,
            connectivity=4,
        )

        component_areas = [
            int(stats[idx, cv2.CC_STAT_AREA])
            for idx in range(1, component_count)
        ]

        label_small_components = [
            area
            for area in component_areas
            if area <= min_area
        ]

        total_components += len(component_areas)
        small_components += len(label_small_components)
        small_component_pixels += int(sum(label_small_components))

        labels.append(
            {
                "color_id": int(color_id),
                "pixels": int(color_region.sum()),
                "components": int(len(component_areas)),
                "small_components": int(len(label_small_components)),
                "small_component_pixels": int(sum(label_small_components)),
                "largest_component_pixels": int(max(component_areas, default=0)),
            }
        )

    return {
        "total_components": int(total_components),
        "small_components": int(small_components),
        "small_component_pixels": int(small_component_pixels),
        "unassigned_pixels": int(unassigned_pixels),
        "labels": labels,
    }


def clean_color_islands(
    local_label_map: np.ndarray,
    mask: np.ndarray,
    min_area: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    result = local_label_map.copy()

    if min_area <= 0:
        return result, {
            "merged_components": 0,
            "merged_pixels": 0,
            "protected_largest_components": 0,
            "unmerged_components": 0,
            "passes": 0,
        }

    merged_components = 0
    merged_pixels = 0
    protected_largest_components = 0
    unmerged_components = 0
    passes = 1

    for color_id in sorted(int(x) for x in np.unique(result[mask]) if int(x) >= 0):
        color_region = ((result == color_id) & mask).astype(np.uint8)

        component_count, component_map, stats, _ = cv2.connectedComponentsWithStats(
            color_region,
            connectivity=4,
        )

        if component_count <= 1:
            continue

        component_areas = {
            idx: int(stats[idx, cv2.CC_STAT_AREA])
            for idx in range(1, component_count)
        }

        largest_component = max(
            component_areas,
            key=lambda idx: component_areas[idx],
        )

        for component_id, area in component_areas.items():
            if area > min_area:
                continue

            if component_id == largest_component:
                protected_largest_components += 1
                continue

            target_label = choose_neighbor_label(
                label_map=result,
                component_map=component_map,
                component_id=component_id,
                stats=stats,
                mask=mask,
                current_label=color_id,
            )

            if target_label is None:
                unmerged_components += 1
                continue

            x = int(stats[component_id, cv2.CC_STAT_LEFT])
            y = int(stats[component_id, cv2.CC_STAT_TOP])
            w = int(stats[component_id, cv2.CC_STAT_WIDTH])
            h = int(stats[component_id, cv2.CC_STAT_HEIGHT])

            component_crop = component_map[y:y + h, x:x + w] == component_id
            result_crop = result[y:y + h, x:x + w]
            result_crop[component_crop] = target_label

            merged_components += 1
            merged_pixels += area

    return result, {
        "merged_components": int(merged_components),
        "merged_pixels": int(merged_pixels),
        "protected_largest_components": int(protected_largest_components),
        "unmerged_components": int(unmerged_components),
        "passes": int(passes),
    }


def choose_neighbor_label(
    label_map: np.ndarray,
    component_map: np.ndarray,
    component_id: int,
    stats: np.ndarray,
    mask: np.ndarray,
    current_label: int,
) -> int | None:
    x = int(stats[component_id, cv2.CC_STAT_LEFT])
    y = int(stats[component_id, cv2.CC_STAT_TOP])
    w = int(stats[component_id, cv2.CC_STAT_WIDTH])
    h = int(stats[component_id, cv2.CC_STAT_HEIGHT])

    y1 = max(y - 1, 0)
    x1 = max(x - 1, 0)
    y2 = min(y + h + 1, label_map.shape[0])
    x2 = min(x + w + 1, label_map.shape[1])

    component_crop = component_map[y1:y2, x1:x2] == component_id

    dilated = cv2.dilate(
        component_crop.astype(np.uint8),
        np.ones((3, 3), np.uint8),
        iterations=1,
    ).astype(bool)

    border = dilated & ~component_crop & mask[y1:y2, x1:x2]

    neighbor_labels = label_map[y1:y2, x1:x2][border]
    neighbor_labels = neighbor_labels[
        (neighbor_labels >= 0)
        & (neighbor_labels != current_label)
    ]

    if len(neighbor_labels) == 0:
        return None

    values, counts = np.unique(neighbor_labels, return_counts=True)

    return int(values[int(np.argmax(counts))])


def fill_unassigned_by_neighbors(
    label_map: np.ndarray,
    mask: np.ndarray,
    max_iter: int = 20,
) -> np.ndarray:
    result = label_map.copy()

    for _ in range(max_iter):
        missing = (result == -1) & mask

        if not missing.any():
            break

        padded = np.pad(result, 1, mode="edge")

        new_result = result.copy()

        ys, xs = np.where(missing)

        for y, x in zip(ys, xs):
            neighbors = [
                padded[y, x + 1],
                padded[y + 2, x + 1],
                padded[y + 1, x],
                padded[y + 1, x + 2],
            ]

            neighbors = [n for n in neighbors if n >= 0]

            if neighbors:
                values, counts = np.unique(neighbors, return_counts=True)
                new_result[y, x] = int(values[np.argmax(counts)])

        result = new_result

    missing = (result == -1) & mask

    if missing.any():
        valid = result[mask & (result >= 0)]

        fallback = int(np.bincount(valid).argmax()) if len(valid) else 0

        result[missing] = fallback

    return result


def smooth_object(
    image_rgb: np.ndarray,
    mask: np.ndarray,
    colors_per_object: int,
    min_region_area: int,
    preserve_internal_details: bool = True,
) -> tuple[np.ndarray, dict[str, Any]]:
    output = image_rgb.copy()

    if preserve_internal_details:
        detail_mask, detail_diagnostics = detect_internal_detail_mask(
            image_rgb=image_rgb,
            mask=mask,
            min_region_area=min_region_area,
        )
    else:
        detail_mask = np.zeros(mask.shape, dtype=bool)
        detail_diagnostics = {
            "enabled": False,
            "skipped": True,
            "reason": "disabled",
            "component_count": 0,
            "pixels": 0,
        }

    smoothing_mask = mask & ~detail_mask
    pixels = image_rgb[smoothing_mask]

    if len(pixels) < min_region_area:
        output[detail_mask] = image_rgb[detail_mask]
        return output, {
            "skipped": True,
            "mask_pixels": int(mask.sum()),
            "smoothing_pixels": int(len(pixels)),
            "requested_colors": int(colors_per_object),
            "effective_colors": 0,
            "detail_preservation": detail_diagnostics,
        }

    labels, palette_rgb = dominant_colors_lab(
        rgb_pixels=pixels,
        k=colors_per_object,
    )

    local_map = np.full(mask.shape, -1, dtype=np.int32)
    local_map[smoothing_mask] = labels.astype(np.int32)

    before_cleanup = color_component_stats(
        local_label_map=local_map,
        mask=smoothing_mask,
        min_area=min_region_area,
    )

    local_map, cleanup_stats = clean_color_islands(
        local_label_map=local_map,
        mask=smoothing_mask,
        min_area=min_region_area,
    )

    after_island_cleanup = color_component_stats(
        local_label_map=local_map,
        mask=smoothing_mask,
        min_area=min_region_area,
    )

    unassigned_before_fill = int(((local_map == -1) & smoothing_mask).sum())

    local_map = fill_unassigned_by_neighbors(
        label_map=local_map,
        mask=smoothing_mask,
    )

    after_fill = color_component_stats(
        local_label_map=local_map,
        mask=smoothing_mask,
        min_area=min_region_area,
    )

    for color_id, color in enumerate(palette_rgb):
        output[(local_map == color_id) & smoothing_mask] = color.astype(np.uint8)

    output[detail_mask] = image_rgb[detail_mask]

    diagnostics = {
        "skipped": False,
        "mask_pixels": int(mask.sum()),
        "smoothing_pixels": int(len(pixels)),
        "requested_colors": int(colors_per_object),
        "effective_colors": int(len(palette_rgb)),
        "min_region_area": int(min_region_area),
        "detail_preservation": detail_diagnostics,
        "before_cleanup": before_cleanup,
        "after_island_cleanup": after_island_cleanup,
        "after_fill": after_fill,
        "cleanup": cleanup_stats,
        "components_removed_by_island_cleanup": int(
            before_cleanup["total_components"]
            - after_island_cleanup["total_components"]
        ),
        "small_components_removed_by_island_cleanup": int(
            before_cleanup["small_components"]
            - after_island_cleanup["small_components"]
        ),
        "unassigned_pixels_filled": int(unassigned_before_fill),
    }

    return output, diagnostics


def smooth_background(
    image_rgb: np.ndarray,
    covered_mask: np.ndarray,
    colors: int = 6,
    min_region_area: int = 500,
) -> tuple[np.ndarray, dict[str, Any]]:
    bg_mask = ~covered_mask

    if bg_mask.sum() < 100:
        return image_rgb, {
            "skipped": True,
            "mask_pixels": int(bg_mask.sum()),
            "requested_colors": int(colors),
            "effective_colors": 0,
        }

    output, diagnostics = smooth_object(
        image_rgb=image_rgb,
        mask=bg_mask,
        colors_per_object=colors,
        min_region_area=min_region_area,
        preserve_internal_details=False,
    )

    return output, diagnostics


def run_step2_smooth_segments(
    image_path: str,
    metadata_path: str,
    output_dir: str,
    colors_per_object: int = 5,
    background_colors: int = 6,
    min_region_area: int = 300,
    process_background: bool = True,
    max_objects: int = 80,
) -> dict[str, Any]:
    ensure_dir(output_dir)

    objects_smoothed_dir = os.path.join(output_dir, "objects_smoothed")
    ensure_dir(objects_smoothed_dir)

    image_rgb = read_rgb(image_path)

    h, w = image_rgb.shape[:2]

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    metadata = sorted(
        metadata,
        key=lambda x: int(x["area"]),
        reverse=True,
    )

    metadata = metadata[:max_objects]

    final = image_rgb.copy()

    covered_mask = np.zeros((h, w), dtype=bool)

    processed_objects = 0
    skipped_objects = 0

    object_outputs: list[dict[str, Any]] = []

    for item in metadata:
        obj_id = int(item["id"])
        mask_path = str(item["mask_path"])

        mask = read_mask(mask_path)

        if mask.shape != (h, w):
            raise ValueError(
                f"Mask shape mismatch for object {obj_id}: "
                f"mask={mask.shape}, image={(h, w)}"
            )

        effective_mask = mask & ~covered_mask

        effective_area = int(effective_mask.sum())

        if effective_area < min_region_area:
            skipped_objects += 1
            continue

        smoothed_full, object_diagnostics = smooth_object(
            image_rgb=image_rgb,
            mask=effective_mask,
            colors_per_object=colors_per_object,
            min_region_area=min_region_area,
            preserve_internal_details=True,
        )

        final[effective_mask] = smoothed_full[effective_mask]
        covered_mask |= effective_mask

        x1, y1, x2, y2 = item["bbox_xyxy"]

        crop = final[y1:y2 + 1, x1:x2 + 1]
        crop_mask = effective_mask[y1:y2 + 1, x1:x2 + 1]

        alpha = np.where(crop_mask, 255, 0).astype(np.uint8)
        rgba = np.dstack([crop, alpha])

        object_output_path = os.path.join(
            objects_smoothed_dir,
            f"object_{obj_id:03d}.png",
        )

        Image.fromarray(rgba).save(object_output_path)

        object_outputs.append(
            {
                "id": obj_id,
                "area": effective_area,
                "output_path": object_output_path,
                "diagnostics": object_diagnostics,
            }
        )

        processed_objects += 1

    if process_background:
        bg_smoothed, background_diagnostics = smooth_background(
            image_rgb=image_rgb,
            covered_mask=covered_mask,
            colors=background_colors,
            min_region_area=max(min_region_area, 500),
        )

        final[~covered_mask] = bg_smoothed[~covered_mask]
    else:
        background_diagnostics = {
            "skipped": True,
            "reason": "process_background disabled",
            "mask_pixels": int((~covered_mask).sum()),
            "requested_colors": int(background_colors),
            "effective_colors": 0,
        }

    smoothed_path = os.path.join(output_dir, "step2_smoothed.png")
    covered_mask_path = os.path.join(output_dir, "covered_mask.png")
    result_path = os.path.join(output_dir, "step2_result.json")

    Image.fromarray(final).save(smoothed_path)

    cv2.imwrite(
        covered_mask_path,
        np.where(covered_mask, 255, 0).astype(np.uint8),
    )

    result = {
        "step": 2,
        "image_width": int(w),
        "image_height": int(h),
        "processed_objects": int(processed_objects),
        "skipped_objects": int(skipped_objects),
        "covered_pixels": int(covered_mask.sum()),
        "covered_ratio": float(covered_mask.sum() / (h * w)),
        "params": {
            "colors_per_object": int(colors_per_object),
            "background_colors": int(background_colors),
            "min_region_area": int(min_region_area),
            "process_background": bool(process_background),
            "max_objects": int(max_objects),
        },
        "diagnostics": {
            "objects": [
                {
                    "id": int(item["id"]),
                    "area": int(item["area"]),
                    "diagnostics": item["diagnostics"],
                }
                for item in object_outputs
            ],
            "background": background_diagnostics,
            "detail_components_protected": int(
                sum(
                    item["diagnostics"]
                    .get("detail_preservation", {})
                    .get("component_count", 0)
                    for item in object_outputs
                )
            ),
            "detail_pixels_protected": int(
                sum(
                    item["diagnostics"]
                    .get("detail_preservation", {})
                    .get("pixels", 0)
                    for item in object_outputs
                )
            ),
            "total_components_before_cleanup": int(
                sum(
                    item["diagnostics"]
                    .get("before_cleanup", {})
                    .get("total_components", 0)
                    for item in object_outputs
                )
            ),
            "small_components_before_cleanup": int(
                sum(
                    item["diagnostics"]
                    .get("before_cleanup", {})
                    .get("small_components", 0)
                    for item in object_outputs
                )
            ),
            "small_component_pixels_before_cleanup": int(
                sum(
                    item["diagnostics"]
                    .get("before_cleanup", {})
                    .get("small_component_pixels", 0)
                    for item in object_outputs
                )
            ),
            "unassigned_pixels_filled": int(
                sum(
                    item["diagnostics"].get("unassigned_pixels_filled", 0)
                    for item in object_outputs
                )
            ),
            "total_components_after_island_cleanup": int(
                sum(
                    item["diagnostics"]
                    .get("after_island_cleanup", {})
                    .get("total_components", 0)
                    for item in object_outputs
                )
            ),
            "small_components_after_island_cleanup": int(
                sum(
                    item["diagnostics"]
                    .get("after_island_cleanup", {})
                    .get("small_components", 0)
                    for item in object_outputs
                )
            ),
            "total_components_after_fill": int(
                sum(
                    item["diagnostics"]
                    .get("after_fill", {})
                    .get("total_components", 0)
                    for item in object_outputs
                )
            ),
            "small_components_after_fill": int(
                sum(
                    item["diagnostics"]
                    .get("after_fill", {})
                    .get("small_components", 0)
                    for item in object_outputs
                )
            ),
            "components_removed_by_island_cleanup": int(
                sum(
                    item["diagnostics"].get(
                        "components_removed_by_island_cleanup",
                        0,
                    )
                    for item in object_outputs
                )
            ),
            "small_components_removed_by_island_cleanup": int(
                sum(
                    item["diagnostics"].get(
                        "small_components_removed_by_island_cleanup",
                        0,
                    )
                    for item in object_outputs
                )
            ),
            "components_merged_by_island_cleanup": int(
                sum(
                    item["diagnostics"]
                    .get("cleanup", {})
                    .get("merged_components", 0)
                    for item in object_outputs
                )
            ),
            "pixels_merged_by_island_cleanup": int(
                sum(
                    item["diagnostics"]
                    .get("cleanup", {})
                    .get("merged_pixels", 0)
                    for item in object_outputs
                )
            ),
            "protected_largest_components": int(
                sum(
                    item["diagnostics"]
                    .get("cleanup", {})
                    .get("protected_largest_components", 0)
                    for item in object_outputs
                )
            ),
        },
        "outputs": {
            "preview": smoothed_path,
            "covered_mask": covered_mask_path,
            "objects_smoothed_dir": objects_smoothed_dir,
            "objects": object_outputs,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result
