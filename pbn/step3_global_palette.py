import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from sklearn.cluster import MiniBatchKMeans


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def read_rgb(path: str) -> np.ndarray:
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)

    if bgr is None:
        raise FileNotFoundError(f"Could not read image: {path}")

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def rgb_to_hex(color: np.ndarray) -> str:
    r, g, b = [int(x) for x in color]

    return f"#{r:02X}{g:02X}{b:02X}"


def build_global_palette(
    image_rgb: np.ndarray,
    palette_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    pixels = image_rgb.reshape(-1, 3)

    lab_pixels = cv2.cvtColor(
        pixels.reshape(-1, 1, 3),
        cv2.COLOR_RGB2LAB,
    ).reshape(-1, 3).astype(np.float32)

    palette_size = max(1, min(palette_size, len(lab_pixels)))

    kmeans = MiniBatchKMeans(
        n_clusters=palette_size,
        random_state=42,
        batch_size=8192,
        n_init="auto",
    )

    labels = kmeans.fit_predict(lab_pixels).astype(np.int32)

    centers_lab = kmeans.cluster_centers_.astype(np.uint8)

    centers_rgb = cv2.cvtColor(
        centers_lab.reshape(-1, 1, 3),
        cv2.COLOR_LAB2RGB,
    ).reshape(-1, 3)

    return labels, centers_rgb.astype(np.uint8)


def sort_palette_by_lightness(palette_rgb: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(
        palette_rgb.reshape(-1, 1, 3),
        cv2.COLOR_RGB2LAB,
    ).reshape(-1, 3)

    return np.argsort(lab[:, 0])


def remap_labels(
    labels: np.ndarray,
    order: np.ndarray,
) -> np.ndarray:
    old_to_new = {
        int(old): int(new)
        for new, old in enumerate(order)
    }

    return np.array(
        [old_to_new[int(x)] for x in labels],
        dtype=np.int32,
    )


def save_palette_preview(
    palette_rgb: np.ndarray,
    output_path: str,
    swatch_size: int = 80,
) -> None:
    count = len(palette_rgb)

    width = swatch_size * count
    height = swatch_size

    preview = np.zeros((height, width, 3), dtype=np.uint8)

    for i, color in enumerate(palette_rgb):
        x1 = i * swatch_size
        x2 = x1 + swatch_size

        preview[:, x1:x2] = color.astype(np.uint8)

    Image.fromarray(preview).save(output_path)


def run_step3_global_palette(
    image_path: str,
    output_dir: str,
    palette_size: int = 30,
) -> dict[str, Any]:
    ensure_dir(output_dir)

    image_rgb = read_rgb(image_path)

    h, w = image_rgb.shape[:2]

    labels, palette_rgb = build_global_palette(
        image_rgb=image_rgb,
        palette_size=palette_size,
    )

    order = sort_palette_by_lightness(palette_rgb)

    palette_rgb = palette_rgb[order]

    labels = remap_labels(
        labels=labels,
        order=order,
    )

    label_map = labels.reshape(h, w)

    quantized = palette_rgb[label_map]

    palette_image_path = str(Path(output_dir) / "step3_palette_image.png")
    color_ids_path = str(Path(output_dir) / "step3_color_ids.png")
    palette_preview_path = str(Path(output_dir) / "palette_preview.png")
    palette_json_path = str(Path(output_dir) / "palette.json")
    label_map_path = str(Path(output_dir) / "label_map.npy")
    result_path = str(Path(output_dir) / "step3_result.json")

    Image.fromarray(quantized.astype(np.uint8)).save(palette_image_path)

    color_ids_vis = (
        label_map.astype(np.float32)
        / max(int(label_map.max()), 1)
        * 255
    ).astype(np.uint8)

    cv2.imwrite(color_ids_path, color_ids_vis)

    save_palette_preview(
        palette_rgb=palette_rgb,
        output_path=palette_preview_path,
    )

    palette_data: list[dict[str, Any]] = []

    for idx, color in enumerate(palette_rgb, start=1):
        palette_data.append(
            {
                "number": int(idx),
                "rgb": [int(x) for x in color],
                "hex": rgb_to_hex(color),
            }
        )

    with open(palette_json_path, "w", encoding="utf-8") as f:
        json.dump(palette_data, f, indent=2)

    np.save(label_map_path, label_map)

    result = {
        "step": 3,
        "image_width": int(w),
        "image_height": int(h),
        "palette_size": int(len(palette_rgb)),
        "params": {
            "palette_size": int(palette_size),
        },
        "outputs": {
            "preview": palette_image_path,
            "color_ids": color_ids_path,
            "palette_preview": palette_preview_path,
            "palette": palette_json_path,
            "label_map": label_map_path,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result