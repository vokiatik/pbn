import json
import os
import random
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

import torch

from sam2.build_sam import build_sam2
from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def load_image_rgb(path: str) -> np.ndarray:
    image_bgr = cv2.imread(path, cv2.IMREAD_COLOR)

    if image_bgr is None:
        raise FileNotFoundError(f"Could not read image: {path}")

    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)


def mask_to_bbox(mask: np.ndarray) -> list[int] | None:
    ys, xs = np.where(mask)

    if len(xs) == 0 or len(ys) == 0:
        return None

    return [
        int(xs.min()),
        int(ys.min()),
        int(xs.max()),
        int(ys.max()),
    ]


def crop_object_rgba(
    image_rgb: np.ndarray,
    mask: np.ndarray,
    bbox: list[int],
) -> np.ndarray:
    x1, y1, x2, y2 = bbox

    crop_rgb = image_rgb[y1:y2 + 1, x1:x2 + 1]
    crop_mask = mask[y1:y2 + 1, x1:x2 + 1]

    alpha = crop_mask.astype(np.uint8) * 255

    return np.dstack([crop_rgb, alpha])


def create_overlay(
    image_rgb: np.ndarray,
    masks: list[dict[str, Any]],
    alpha: float = 0.45,
) -> np.ndarray:
    overlay = image_rgb.copy().astype(np.float32)

    for item in masks:
        mask = item["segmentation"].astype(bool)

        color = np.array(
            [
                random.randint(40, 255),
                random.randint(40, 255),
                random.randint(40, 255),
            ],
            dtype=np.float32,
        )

        overlay[mask] = overlay[mask] * (1 - alpha) + color * alpha

    return np.clip(overlay, 0, 255).astype(np.uint8)


def create_label_map(
    image_shape: tuple[int, int, int],
    masks: list[dict[str, Any]],
) -> np.ndarray:
    h, w = image_shape[:2]

    label_map = np.zeros((h, w), dtype=np.uint16)

    sorted_masks = sorted(
        masks,
        key=lambda item: int(item["area"]),
        reverse=True,
    )

    for idx, item in enumerate(sorted_masks, start=1):
        mask = item["segmentation"].astype(bool)
        label_map[mask] = idx

    return label_map


def filter_masks(
    masks: list[dict[str, Any]],
    image_area: int,
    min_area_ratio: float,
    max_area_ratio: float,
    min_stability: float,
    min_pred_iou: float,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for item in masks:
        area = int(item["area"])
        area_ratio = area / image_area

        if area_ratio < min_area_ratio:
            continue

        if area_ratio > max_area_ratio:
            continue

        if float(item.get("stability_score", 0)) < min_stability:
            continue

        if float(item.get("predicted_iou", 0)) < min_pred_iou:
            continue

        result.append(item)

    return result


def remove_duplicate_like_masks(
    masks: list[dict[str, Any]],
    iou_threshold: float = 0.92,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []

    sorted_masks = sorted(
        masks,
        key=lambda item: (
            float(item.get("predicted_iou", 0)),
            int(item["area"]),
        ),
        reverse=True,
    )

    for item in sorted_masks:
        mask = item["segmentation"].astype(bool)

        duplicate = False

        for kept_item in kept:
            kept_mask = kept_item["segmentation"].astype(bool)

            inter = np.logical_and(mask, kept_mask).sum()
            union = np.logical_or(mask, kept_mask).sum()

            if union == 0:
                continue

            iou = inter / union

            if iou >= iou_threshold:
                duplicate = True
                break

        if not duplicate:
            kept.append(item)

    return kept


def resolve_sam2_paths(
    checkpoint: str | None,
    model_cfg: str | None,
) -> tuple[str, str]:
    resolved_checkpoint = checkpoint or os.getenv(
        "SAM2_CHECKPOINT",
        "checkpoints/sam2.1_hiera_base_plus.pt",
    )

    resolved_model_cfg = model_cfg or os.getenv(
        "SAM2_MODEL_CFG",
        "configs/sam2.1/sam2.1_hiera_b+.yaml",
    )

    return resolved_checkpoint, resolved_model_cfg


def run_step1_sam_objects(
    image_path: str,
    output_dir: str,
    checkpoint: str | None = None,
    model_cfg: str | None = None,
    points_per_side: int = 32,
    pred_iou_thresh: float = 0.88,
    stability_score_thresh: float = 0.92,
    min_mask_region_area: int = 400,
    min_area_ratio: float = 0.002,
    max_area_ratio: float = 0.80,
    dedupe_iou: float = 0.92,
) -> dict[str, Any]:
    ensure_dir(output_dir)

    masks_dir = str(Path(output_dir) / "masks")
    objects_dir = str(Path(output_dir) / "objects")

    ensure_dir(masks_dir)
    ensure_dir(objects_dir)

    resolved_checkpoint, resolved_model_cfg = resolve_sam2_paths(
        checkpoint=checkpoint,
        model_cfg=model_cfg,
    )

    image_rgb = load_image_rgb(image_path)

    h, w = image_rgb.shape[:2]
    image_area = h * w

    device = "cuda" if torch.cuda.is_available() else "cpu"

    sam2 = build_sam2(
        resolved_model_cfg,
        resolved_checkpoint,
        device=device,
        apply_postprocessing=True,
    )

    mask_generator = SAM2AutomaticMaskGenerator(
        model=sam2,
        points_per_side=int(points_per_side),
        pred_iou_thresh=float(pred_iou_thresh),
        stability_score_thresh=float(stability_score_thresh),
        min_mask_region_area=int(min_mask_region_area),
    )

    masks = mask_generator.generate(image_rgb)

    raw_mask_count = len(masks)

    masks = filter_masks(
        masks=masks,
        image_area=image_area,
        min_area_ratio=float(min_area_ratio),
        max_area_ratio=float(max_area_ratio),
        min_stability=float(stability_score_thresh),
        min_pred_iou=float(pred_iou_thresh),
    )

    filtered_mask_count = len(masks)

    masks = remove_duplicate_like_masks(
        masks=masks,
        iou_threshold=float(dedupe_iou),
    )

    final_mask_count = len(masks)

    masks = sorted(
        masks,
        key=lambda item: int(item["area"]),
        reverse=True,
    )

    metadata: list[dict[str, Any]] = []

    for idx, item in enumerate(masks, start=1):
        mask = item["segmentation"].astype(bool)

        bbox = mask_to_bbox(mask)

        if bbox is None:
            continue

        mask_img = mask.astype(np.uint8) * 255

        mask_path = str(Path(masks_dir) / f"mask_{idx:03d}.png")
        object_path = str(Path(objects_dir) / f"object_{idx:03d}.png")

        cv2.imwrite(mask_path, mask_img)

        rgba = crop_object_rgba(
            image_rgb=image_rgb,
            mask=mask,
            bbox=bbox,
        )

        Image.fromarray(rgba).save(object_path)

        metadata.append(
            {
                "id": int(idx),
                "area": int(item["area"]),
                "area_ratio": float(item["area"] / image_area),
                "bbox_xyxy": bbox,
                "predicted_iou": float(item.get("predicted_iou", 0)),
                "stability_score": float(item.get("stability_score", 0)),
                "mask_path": mask_path,
                "object_path": object_path,
            }
        )

    overlay_path = str(Path(output_dir) / "overlay.png")
    labels_path = str(Path(output_dir) / "labels.png")
    labels_raw_path = str(Path(output_dir) / "labels_raw_16bit.png")
    metadata_path = str(Path(output_dir) / "metadata.json")
    result_path = str(Path(output_dir) / "step1_result.json")

    overlay = create_overlay(
        image_rgb=image_rgb,
        masks=masks,
    )

    Image.fromarray(overlay).save(overlay_path)

    label_map = create_label_map(
        image_shape=image_rgb.shape,
        masks=masks,
    )

    label_vis = (
        label_map.astype(np.float32)
        / max(int(label_map.max()), 1)
        * 255
    ).astype(np.uint8)

    cv2.imwrite(labels_path, label_vis)
    cv2.imwrite(labels_raw_path, label_map)

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    result = {
        "step": 1,
        "image_width": int(w),
        "image_height": int(h),
        "device": device,
        "raw_mask_count": int(raw_mask_count),
        "filtered_mask_count": int(filtered_mask_count),
        "final_mask_count": int(final_mask_count),
        "params": {
            "checkpoint": resolved_checkpoint,
            "model_cfg": resolved_model_cfg,
            "points_per_side": int(points_per_side),
            "pred_iou_thresh": float(pred_iou_thresh),
            "stability_score_thresh": float(stability_score_thresh),
            "min_mask_region_area": int(min_mask_region_area),
            "min_area_ratio": float(min_area_ratio),
            "max_area_ratio": float(max_area_ratio),
            "dedupe_iou": float(dedupe_iou),
        },
        "outputs": {
            "overlay": overlay_path,
            "labels": labels_path,
            "labels_raw": labels_raw_path,
            "metadata": metadata_path,
            "masks_dir": masks_dir,
            "objects_dir": objects_dir,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result