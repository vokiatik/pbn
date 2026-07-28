from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color, segmentation
from sklearn.cluster import KMeans
from threadpoolctl import threadpool_limits

from .io_utils import atomic_write_json, save_rgb
from .print_spec import PrintSpec, mm_to_px


ASSESSMENT_MAX_DIMENSION = 768
ASSESSMENT_SUPERPIXELS = 1225
MEAN_DELTA_E_WARNING = 6.0
P90_DELTA_E_WARNING = 12.0
MICRO_DETAIL_AREA_WARNING_PERCENT = 3.0
REGION_COUNT_WARNING = 1155


def assess_ai_source(
    image_path: Path,
    output_dir: Path,
    target_palette_size: int,
    print_spec: PrintSpec,
) -> dict[str, object]:
    """Produce a deterministic, advisory estimate of downstream PBN complexity."""
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image.thumbnail((ASSESSMENT_MAX_DIMENSION, ASSESSMENT_MAX_DIMENSION), Image.Resampling.LANCZOS)
        rgb = np.asarray(image, dtype=np.uint8)

    superpixel_count = min(ASSESSMENT_SUPERPIXELS, max(32, rgb.shape[0] * rgb.shape[1] // 64))
    labels = segmentation.slic(
        rgb,
        n_segments=superpixel_count,
        compactness=10.0,
        sigma=0.6,
        start_label=1,
        enforce_connectivity=True,
        slic_zero=True,
        convert2lab=True,
        channel_axis=-1,
    ).astype(np.int32)
    source_lab = color.rgb2lab(rgb.astype(np.float64) / 255.0)
    region_ids = [int(value) for value in np.unique(labels) if int(value) > 0]
    samples: list[np.ndarray] = []
    areas: list[int] = []
    for region_id in region_ids:
        mask = labels == region_id
        samples.append(np.median(source_lab[mask], axis=0))
        areas.append(int(mask.sum()))
    sample_array = np.asarray(samples, dtype=np.float64)
    area_array = np.asarray(areas, dtype=np.float64)
    unique_count = len(np.unique(np.round(sample_array, decimals=5), axis=0))
    cluster_count = min(max(1, int(target_palette_size)), len(region_ids), unique_count)
    if cluster_count == 1:
        centers = np.average(sample_array, axis=0, weights=np.sqrt(area_array))[None, :]
        assignments = np.zeros(len(region_ids), dtype=np.int32)
    else:
        model = KMeans(n_clusters=cluster_count, random_state=0, n_init=10, algorithm="lloyd")
        with threadpool_limits(limits=1):
            assignments = model.fit_predict(
                sample_array,
                sample_weight=np.sqrt(area_array),
            ).astype(np.int32)
        centers = model.cluster_centers_

    assignment_lut = np.zeros(int(labels.max()) + 1, dtype=np.int32)
    for region_id, cluster_id in zip(region_ids, assignments, strict=True):
        assignment_lut[region_id] = int(cluster_id)
    cluster_map = assignment_lut[labels]
    reconstructed_lab = centers[cluster_map]
    delta = color.deltaE_ciede2000(source_lab, reconstructed_lab)
    mean_delta = float(np.mean(delta))
    p90_delta = float(np.percentile(delta, 90))
    reconstructed_region_count, micro_detail_area_percent = _component_complexity(cluster_map, print_spec)
    source_colour_count = len(np.unique(rgb.reshape(-1, 3), axis=0))
    estimated_regions = (
        reconstructed_region_count
        if source_colour_count <= target_palette_size
        else len(region_ids)
    )
    codes: list[str] = []
    if mean_delta > MEAN_DELTA_E_WARNING or p90_delta > P90_DELTA_E_WARNING:
        codes.append("palette_mismatch")
    if micro_detail_area_percent > MICRO_DETAIL_AREA_WARNING_PERCENT:
        codes.append("micro_detail_density")
    if estimated_regions > REGION_COUNT_WARNING:
        codes.append("region_complexity")

    status = "warn" if codes else "pass"
    message = (
        "The AI image may lose fine detail during conversion. You can continue or regenerate with larger, flatter colour areas."
        if codes
        else "The AI image is a good candidate for local paint-by-number conversion."
    )
    report: dict[str, object] = {
        "status": status,
        "codes": codes,
        "message": message,
        "metrics": {
            "mean_delta_e_00": round(mean_delta, 6),
            "p90_delta_e_00": round(p90_delta, 6),
            "estimated_region_count": estimated_regions,
            "micro_detail_area_percent": round(micro_detail_area_percent, 6),
        },
        "thresholds": {
            "mean_delta_e_00": MEAN_DELTA_E_WARNING,
            "p90_delta_e_00": P90_DELTA_E_WARNING,
            "estimated_region_count": REGION_COUNT_WARNING,
            "micro_detail_area_percent": MICRO_DETAIL_AREA_WARNING_PERCENT,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "quality_report.json", report)
    preview_rgb = np.clip(
        np.rint(color.lab2rgb(reconstructed_lab) * 255.0),
        0,
        255,
    ).astype(np.uint8)
    save_rgb(output_dir / "quality_preview.png", preview_rgb)
    return report


def _component_complexity(cluster_map: np.ndarray, print_spec: PrintSpec) -> tuple[int, float]:
    page_width, page_height = print_spec.page_px
    margin = mm_to_px(print_spec.margin_mm, print_spec.dpi)
    scale = min(
        (page_width - 2 * margin) / cluster_map.shape[1],
        (page_height - 2 * margin) / cluster_map.shape[0],
    )
    mm_per_pixel = scale * 25.4 / print_spec.dpi
    pixel_area_mm2 = mm_per_pixel**2
    structure = np.asarray([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    region_count = 0
    micro_pixels = 0
    for cluster_id in np.unique(cluster_map):
        mask = cluster_map == cluster_id
        component_map, count = ndimage.label(mask, structure=structure)
        if count == 0:
            continue
        region_count += int(count)
        areas = np.bincount(component_map.ravel(), minlength=count + 1)[1:]
        distance = ndimage.distance_transform_edt(mask)
        radii = ndimage.maximum(distance, labels=component_map, index=np.arange(1, count + 1))
        widths_mm = np.maximum(0.0, 2.0 * np.asarray(radii) - 1.0) * mm_per_pixel
        label_pockets_mm = widths_mm
        invalid = (
            (areas * pixel_area_mm2 < 12.0)
            | (widths_mm < 1.5)
            | (label_pockets_mm < 4.0)
        )
        micro_pixels += int(np.sum(areas[invalid]))
    return region_count, 100.0 * micro_pixels / max(1, cluster_map.size)
