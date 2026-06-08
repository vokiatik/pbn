import os
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from sklearn.cluster import MiniBatchKMeans
from skimage.morphology import remove_small_objects


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def read_rgb(path: str) -> np.ndarray:
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


def clean_color_islands(
    local_label_map: np.ndarray,
    mask: np.ndarray,
    min_area: int,
) -> np.ndarray:
    result = local_label_map.copy()

    unique_colors = np.unique(local_label_map[mask])

    for color_id in unique_colors:
        color_region = (local_label_map == color_id) & mask

        cleaned = remove_small_objects(
            color_region,
            min_size=min_area,
            connectivity=1,
        )

        removed = color_region & ~cleaned

        result[removed] = -1

    return result


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
) -> np.ndarray:
    output = image_rgb.copy()

    pixels = image_rgb[mask]

    if len(pixels) < min_region_area:
        return output

    labels, palette_rgb = dominant_colors_lab(
        rgb_pixels=pixels,
        k=colors_per_object,
    )

    local_map = np.full(mask.shape, -1, dtype=np.int32)
    local_map[mask] = labels.astype(np.int32)

    local_map = clean_color_islands(
        local_label_map=local_map,
        mask=mask,
        min_area=min_region_area,
    )

    local_map = fill_unassigned_by_neighbors(
        label_map=local_map,
        mask=mask,
    )

    for color_id, color in enumerate(palette_rgb):
        output[(local_map == color_id) & mask] = color.astype(np.uint8)

    return output


def smooth_background(
    image_rgb: np.ndarray,
    covered_mask: np.ndarray,
    colors: int = 6,
    min_region_area: int = 500,
) -> np.ndarray:
    bg_mask = ~covered_mask

    if bg_mask.sum() < 100:
        return image_rgb

    return smooth_object(
        image_rgb=image_rgb,
        mask=bg_mask,
        colors_per_object=colors,
        min_region_area=min_region_area,
    )


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

        smoothed_full = smooth_object(
            image_rgb=image_rgb,
            mask=effective_mask,
            colors_per_object=colors_per_object,
            min_region_area=min_region_area,
        )

        final[effective_mask] = smoothed_full[effective_mask]
        covered_mask |= effective_mask

        x1, y1, x2, y2 = item["bbox_xyxy"]

        crop = final[y1:y2 + 1, x1:x2 + 1]
        crop_mask = effective_mask[y1:y2 + 1, x1:x2 + 1]

        alpha = crop_mask.astype(np.uint8) * 255
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
            }
        )

        processed_objects += 1

    if process_background:
        bg_smoothed = smooth_background(
            image_rgb=image_rgb,
            covered_mask=covered_mask,
            colors=background_colors,
            min_region_area=max(min_region_area, 500),
        )

        final[~covered_mask] = bg_smoothed[~covered_mask]

    smoothed_path = os.path.join(output_dir, "step2_smoothed.png")
    covered_mask_path = os.path.join(output_dir, "covered_mask.png")
    result_path = os.path.join(output_dir, "step2_result.json")

    Image.fromarray(final).save(smoothed_path)

    cv2.imwrite(
        covered_mask_path,
        covered_mask.astype(np.uint8) * 255,
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