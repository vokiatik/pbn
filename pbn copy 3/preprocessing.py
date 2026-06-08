from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from skimage import color

try:
    from skimage.metrics import structural_similarity as _structural_similarity
except Exception:  # pragma: no cover - optional dependency
    _structural_similarity = None

from .edges import build_edge_strength_map
from .pbn_config import CartoonPreprocessConfig


@dataclass
class CartoonPreprocessResult:
    selected_rgb: np.ndarray
    edge_map: np.ndarray
    protected_edges: np.ndarray
    selected_name: str
    selected_metrics: dict[str, float]
    debug_images: dict[str, np.ndarray]


def resize_keep_aspect(image_rgb: np.ndarray, target_longest_side: int) -> np.ndarray:
    h, w = image_rgb.shape[:2]
    longest = max(h, w)
    if longest <= target_longest_side:
        return image_rgb

    scale = target_longest_side / float(longest)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(image_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)


def edge_preserving_smooth(image_rgb: np.ndarray, strength: float) -> np.ndarray:
    strength = float(np.clip(strength, 0.2, 3.0))
    sigma_color = 30.0 * strength
    sigma_space = 12.0 * strength
    bilateral = cv2.bilateralFilter(image_rgb, d=9, sigmaColor=sigma_color, sigmaSpace=sigma_space)

    ximgproc = getattr(cv2, "ximgproc", None)
    if ximgproc is not None and hasattr(ximgproc, "guidedFilter"):
        try:
            guided = ximgproc.guidedFilter(
                guide=image_rgb,
                src=bilateral,
                radius=max(2, int(round(5 * strength))),
                eps=1e-2,
            )
            return np.clip(guided, 0, 255).astype(np.uint8)
        except Exception:
            return bilateral

    return bilateral


def smooth_image(
    image_rgb: np.ndarray,
    method: str = "mean_shift",
    mean_shift_spatial_radius: int = 10,
    mean_shift_color_radius: int = 16,
    bilateral_sigma_color: float = 60.0,
    bilateral_sigma_space: float = 12.0,
) -> np.ndarray:
    """One-pass smoothing for the simplified pipeline.

    method="mean_shift" uses cv2.pyrMeanShiftFiltering (recommended).
    method="bilateral" uses cv2.bilateralFilter as fallback.
    """
    if method == "mean_shift":
        bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        filtered = cv2.pyrMeanShiftFiltering(
            bgr,
            sp=max(1, int(mean_shift_spatial_radius)),
            sr=max(1, int(mean_shift_color_radius)),
            maxLevel=1,
        )
        return cv2.cvtColor(filtered, cv2.COLOR_BGR2RGB)
    else:
        return cv2.bilateralFilter(
            image_rgb,
            d=9,
            sigmaColor=float(bilateral_sigma_color),
            sigmaSpace=float(bilateral_sigma_space),
        )


def rgb_to_lab(image_rgb: np.ndarray) -> np.ndarray:
    rgb01 = image_rgb.astype(np.float32) / 255.0
    return color.rgb2lab(rgb01).astype(np.float32)


def _u8(image: np.ndarray) -> np.ndarray:
    return np.clip(image, 0, 255).astype(np.uint8)


def _normalize01(image: np.ndarray) -> np.ndarray:
    image = image.astype(np.float32)
    min_value = float(image.min())
    max_value = float(image.max())
    if max_value - min_value <= 1e-8:
        return np.zeros_like(image, dtype=np.float32)
    return ((image - min_value) / (max_value - min_value)).astype(np.float32)


def _extract_mask(semantic_masks: Any | None, name: str) -> np.ndarray | None:
    if semantic_masks is None:
        return None
    if isinstance(semantic_masks, dict):
        mask = semantic_masks.get(name)
    else:
        mask = getattr(semantic_masks, name, None)
    if mask is None:
        return None
    array = np.asarray(mask)
    if array.ndim != 2:
        return None
    return (array > 0).astype(np.uint8) * 255


def _combine_masks(*masks: np.ndarray | None) -> np.ndarray | None:
    valid = [mask for mask in masks if mask is not None]
    if not valid:
        return None
    out = valid[0].astype(np.uint8)
    for mask in valid[1:]:
        out = cv2.max(out, mask.astype(np.uint8))
    return out


def _edge_map_from_rgb(image_rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    canny_fine = cv2.Canny(gray, threshold1=40, threshold2=100, L2gradient=True).astype(np.float32) / 255.0
    canny_coarse = cv2.Canny(gray, threshold1=70, threshold2=170, L2gradient=True).astype(np.float32) / 255.0

    gx3 = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy3 = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    sobel3 = _normalize01(np.sqrt(gx3 * gx3 + gy3 * gy3))

    gx5 = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=5)
    gy5 = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=5)
    sobel5 = _normalize01(np.sqrt(gx5 * gx5 + gy5 * gy5))

    laplacian = _normalize01(np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3)))
    edge = _normalize01(0.22 * canny_fine + 0.18 * canny_coarse + 0.28 * sobel3 + 0.16 * sobel5 + 0.16 * laplacian)
    edge = cv2.GaussianBlur(edge, (0, 0), sigmaX=1.0, sigmaY=1.0)
    return np.clip(edge, 0.0, 1.0).astype(np.float32)


def _protected_edge_mask(edge_map: np.ndarray, semantic_masks: Any | None = None, enabled: bool = True) -> np.ndarray:
    if not enabled:
        return np.zeros_like(edge_map, dtype=np.uint8)

    edge_u8 = np.clip(edge_map * 255.0, 0, 255).astype(np.uint8)
    threshold = max(32, int(round(float(np.percentile(edge_u8, 84.0)))))
    strong = cv2.threshold(edge_u8, threshold, 255, cv2.THRESH_BINARY)[1]
    very_strong = cv2.threshold(edge_u8, max(40, int(round(float(np.percentile(edge_u8, 92.0))))), 255, cv2.THRESH_BINARY)[1]

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    protected = cv2.morphologyEx(strong, cv2.MORPH_CLOSE, kernel, iterations=1)
    protected = cv2.dilate(protected, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)
    protected = cv2.max(protected, very_strong)

    semantic_edges = _combine_masks(
        _extract_mask(semantic_masks, "face"),
        _extract_mask(semantic_masks, "hands"),
        _extract_mask(semantic_masks, "hair"),
        _extract_mask(semantic_masks, "p1"),
    )
    if semantic_edges is not None:
        semantic_edges = cv2.dilate(semantic_edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)
        protected = cv2.max(protected, semantic_edges)

    return protected.astype(np.uint8)


def _edge_density_map(edge_map: np.ndarray) -> np.ndarray:
    return cv2.boxFilter(edge_map.astype(np.float32), ddepth=-1, ksize=(9, 9), normalize=True)


def _feather_mask(mask: np.ndarray, radius: int = 7) -> np.ndarray:
    if radius <= 0:
        return (mask.astype(np.float32) / 255.0).astype(np.float32)
    blurred = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), sigmaX=float(radius), sigmaY=float(radius))
    return np.clip(blurred, 0.0, 1.0).astype(np.float32)


def _rolling_guidance_smooth(
    image_rgb: np.ndarray,
    iterations: int,
    spatial_sigma: float,
    range_sigma: float,
    smooth_weight: np.ndarray,
) -> np.ndarray:
    smooth_weight = np.clip(smooth_weight.astype(np.float32), 0.0, 1.0)
    current = image_rgb.astype(np.uint8)
    guide = current.copy()
    ximgproc = getattr(cv2, "ximgproc", None)
    spatial_sigma = float(max(1.0, spatial_sigma))
    range_sigma = float(max(0.01, range_sigma))
    bilateral_d = max(3, int(round(spatial_sigma * 2.0 + 1.0)))
    guided_radius = max(2, int(round(spatial_sigma)))
    sigma_color = float(np.clip(range_sigma * 255.0, 6.0, 90.0))

    if ximgproc is not None and hasattr(ximgproc, "rollingGuidanceFilter"):
        try:
            filtered = ximgproc.rollingGuidanceFilter(
                current,
                d=-1,
                sigmaColor=sigma_color,
                sigmaSpace=spatial_sigma,
                numOfIter=max(1, int(iterations)),
            )
            return _u8(filtered)
        except Exception:
            pass

    for _ in range(max(1, int(iterations))):
        if ximgproc is not None and hasattr(ximgproc, "guidedFilter"):
            try:
                filtered = ximgproc.guidedFilter(
                    guide=guide,
                    src=current,
                    radius=guided_radius,
                    eps=max(1e-4, (sigma_color / 255.0) ** 2),
                )
            except Exception:
                filtered = cv2.bilateralFilter(current, d=bilateral_d, sigmaColor=sigma_color, sigmaSpace=spatial_sigma)
        else:
            filtered = cv2.bilateralFilter(current, d=bilateral_d, sigmaColor=sigma_color, sigmaSpace=spatial_sigma)

        filtered = _u8(filtered)
        mixed = current.astype(np.float32) * (1.0 - smooth_weight[:, :, None]) + filtered.astype(np.float32) * smooth_weight[:, :, None]
        current = _u8(mixed)
        guide = current

    return current


def _adaptive_mean_shift(
    image_rgb: np.ndarray,
    spatial_radius: int,
    color_radius: int,
    semantic_masks: Any | None = None,
) -> np.ndarray:
    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    spatial_radius = max(1, int(spatial_radius))
    color_radius = max(1, int(color_radius))
    base = cv2.pyrMeanShiftFiltering(bgr, sp=spatial_radius, sr=color_radius, maxLevel=1)

    detail_mask = _combine_masks(
        _extract_mask(semantic_masks, "face"),
        _extract_mask(semantic_masks, "hands"),
        _extract_mask(semantic_masks, "skin"),
        _extract_mask(semantic_masks, "hair"),
        _extract_mask(semantic_masks, "p1"),
    )
    background_mask = _extract_mask(semantic_masks, "background")

    if detail_mask is None and background_mask is None:
        return cv2.cvtColor(base, cv2.COLOR_BGR2RGB)

    detail_variant = cv2.pyrMeanShiftFiltering(
        bgr,
        sp=max(4, spatial_radius - 3),
        sr=max(8, color_radius - 5),
        maxLevel=1,
    )
    background_variant = cv2.pyrMeanShiftFiltering(
        bgr,
        sp=max(spatial_radius, int(round(spatial_radius * 1.35))),
        sr=max(color_radius, int(round(color_radius * 1.30))),
        maxLevel=1,
    )

    merged = base.copy()
    if background_mask is not None:
        bg_alpha = _feather_mask(background_mask, radius=7)[:, :, None]
        merged = _u8(merged.astype(np.float32) * (1.0 - bg_alpha) + background_variant.astype(np.float32) * bg_alpha)
    if detail_mask is not None:
        detail_alpha = _feather_mask(detail_mask, radius=5)[:, :, None]
        merged = _u8(merged.astype(np.float32) * (1.0 - detail_alpha) + detail_variant.astype(np.float32) * detail_alpha)

    return cv2.cvtColor(merged, cv2.COLOR_BGR2RGB)


def _posterize_rgb(image_rgb: np.ndarray, poster_levels: int) -> np.ndarray:
    levels = max(4, int(poster_levels))
    lab = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    l_levels = max(4, levels)
    ab_levels = max(4, levels - 1)
    l_step = 255.0 / float(l_levels - 1)
    ab_step = 255.0 / float(ab_levels - 1)

    lab[:, :, 0] = np.round(lab[:, :, 0] / l_step) * l_step
    lab[:, :, 1] = np.round((lab[:, :, 1] + 128.0) / ab_step) * ab_step - 128.0
    lab[:, :, 2] = np.round((lab[:, :, 2] + 128.0) / ab_step) * ab_step - 128.0
    return cv2.cvtColor(_u8(lab), cv2.COLOR_LAB2RGB)


def _image_edge_strength(image_rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return _normalize01(np.sqrt(gx * gx + gy * gy))


def _restore_lost_structure(
    original_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    protected_edges: np.ndarray,
    semantic_masks: Any | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    orig_edge = _image_edge_strength(original_rgb)
    cand_edge = _image_edge_strength(candidate_rgb)

    protected_focus = protected_edges > 0
    detail_mask = _combine_masks(
        _extract_mask(semantic_masks, "face"),
        _extract_mask(semantic_masks, "hands"),
        _extract_mask(semantic_masks, "hair"),
        _extract_mask(semantic_masks, "p1"),
    )
    if detail_mask is not None:
        protected_focus = np.logical_or(protected_focus, detail_mask > 0)

    focus_loss = np.clip(orig_edge - cand_edge, 0.0, 1.0)
    if np.any(protected_focus):
        focus_values = focus_loss[protected_focus]
        threshold = float(np.percentile(focus_values, 62.0)) if focus_values.size else 0.08
    else:
        threshold = float(np.percentile(focus_loss, 90.0)) if np.any(focus_loss > 0) else 0.08

    lost_edges = (focus_loss > threshold) & protected_focus
    lost_edges = cv2.dilate(lost_edges.astype(np.uint8) * 255, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)
    lost_edges = (lost_edges > 0).astype(np.uint8) * 255

    if not np.any(lost_edges):
        return candidate_rgb, lost_edges

    lost_feather = _feather_mask(lost_edges, radius=7)[:, :, None]
    weak_recover = _rolling_guidance_smooth(
        original_rgb,
        iterations=1,
        spatial_sigma=2.5,
        range_sigma=0.07,
        smooth_weight=np.clip(lost_feather[:, :, 0] * 0.65, 0.0, 1.0),
    )
    restored = candidate_rgb.astype(np.float32) * (1.0 - lost_feather) + weak_recover.astype(np.float32) * lost_feather
    restored = _u8(restored)

    edge_focus = _feather_mask(lost_edges, radius=4)[:, :, None]
    restored = _u8(restored.astype(np.float32) * (1.0 - edge_focus) + original_rgb.astype(np.float32) * edge_focus * 0.45)
    return restored, lost_edges


def _downscale_for_metrics(image_rgb: np.ndarray, longest_side: int = 640) -> np.ndarray:
    h, w = image_rgb.shape[:2]
    longest = max(h, w)
    if longest <= longest_side:
        return image_rgb
    scale = float(longest_side) / float(longest)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(image_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _approx_ssim(gray_a: np.ndarray, gray_b: np.ndarray) -> float:
    if _structural_similarity is not None:
        try:
            return float(_structural_similarity(gray_a, gray_b, data_range=1.0))
        except Exception:
            pass

    mu_a = float(gray_a.mean())
    mu_b = float(gray_b.mean())
    sigma_a = float(gray_a.var())
    sigma_b = float(gray_b.var())
    covariance = float(((gray_a - mu_a) * (gray_b - mu_b)).mean())
    c1 = 0.01 ** 2
    c2 = 0.03 ** 2
    numerator = (2.0 * mu_a * mu_b + c1) * (2.0 * covariance + c2)
    denominator = (mu_a * mu_a + mu_b * mu_b + c1) * (sigma_a + sigma_b + c2)
    if abs(denominator) <= 1e-8:
        return 0.0
    return float(numerator / denominator)


def _quantized_region_stats(image_rgb: np.ndarray) -> tuple[int, int]:
    sample = _downscale_for_metrics(image_rgb, longest_side=560)
    lab = cv2.cvtColor(sample, cv2.COLOR_RGB2LAB)
    l_bin = np.clip(lab[:, :, 0] // 32, 0, 7).astype(np.int32)
    a_bin = np.clip((lab[:, :, 1] + 128) // 32, 0, 7).astype(np.int32)
    b_bin = np.clip((lab[:, :, 2] + 128) // 32, 0, 7).astype(np.int32)
    bins = (l_bin * 64) + (a_bin * 8) + b_bin

    region_count = 0
    tiny_islands = 0
    tiny_area_threshold = max(10, int(round(sample.shape[0] * sample.shape[1] * 0.00045)))

    for label in np.unique(bins):
        mask = (bins == label).astype(np.uint8)
        if not np.any(mask):
            continue
        component_count, component_labels = cv2.connectedComponents(mask, connectivity=4)
        for component_id in range(1, component_count):
            area = int(np.sum(component_labels == component_id))
            region_count += 1
            if area <= tiny_area_threshold:
                tiny_islands += 1
    return region_count, tiny_islands


def _metric_signature(
    original_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    edge_map: np.ndarray,
    protected_edges: np.ndarray,
    semantic_masks: Any | None = None,
) -> dict[str, float]:
    original_small = _downscale_for_metrics(original_rgb)
    candidate_small = _downscale_for_metrics(candidate_rgb)
    if original_small.shape != candidate_small.shape:
        candidate_small = cv2.resize(candidate_small, (original_small.shape[1], original_small.shape[0]), interpolation=cv2.INTER_AREA)

    edge_small = edge_map
    if edge_small.shape != original_small.shape[:2]:
        edge_small = cv2.resize(edge_small, (original_small.shape[1], original_small.shape[0]), interpolation=cv2.INTER_AREA)
    candidate_edge = _image_edge_strength(candidate_small)

    protected_small = cv2.resize(protected_edges, (original_small.shape[1], original_small.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    edge_diff = np.abs(edge_small.astype(np.float32) - candidate_edge.astype(np.float32))
    if np.any(protected_small):
        edge_preservation = 1.0 - float(np.mean(edge_diff[protected_small]))
    else:
        edge_preservation = 1.0 - float(np.mean(edge_diff))
    edge_preservation = float(np.clip(edge_preservation, 0.0, 1.0))

    gray_original = cv2.cvtColor(original_small, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    gray_candidate = cv2.cvtColor(candidate_small, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    structural_similarity = float(np.clip(_approx_ssim(gray_original, gray_candidate), 0.0, 1.0))

    color_similarity = 1.0 - float(np.mean(np.abs(original_small.astype(np.float32) - candidate_small.astype(np.float32))) / 255.0)
    color_similarity = float(np.clip(color_similarity, 0.0, 1.0))

    region_count, tiny_islands = _quantized_region_stats(candidate_small)
    target_regions = max(70, int(round((original_small.shape[0] * original_small.shape[1]) / 14000.0)))
    region_balance = 1.0 - min(1.0, abs(region_count - target_regions) / float(target_regions))
    island_ratio = tiny_islands / float(max(1, region_count))
    island_score = 1.0 - min(1.0, island_ratio / 0.22)

    detail_mask = _combine_masks(
        _extract_mask(semantic_masks, "face"),
        _extract_mask(semantic_masks, "hands"),
        _extract_mask(semantic_masks, "hair"),
        _extract_mask(semantic_masks, "p1"),
    )
    detail_preservation = 1.0
    if detail_mask is not None and np.any(detail_mask):
        detail_small = cv2.resize(detail_mask, (original_small.shape[1], original_small.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        if np.any(detail_small):
            detail_diff = np.abs(edge_small.astype(np.float32) - candidate_edge.astype(np.float32))
            detail_preservation = 1.0 - float(np.mean(detail_diff[detail_small]))
            detail_preservation = float(np.clip(detail_preservation, 0.0, 1.0))

    score = (
        0.31 * edge_preservation
        + 0.20 * structural_similarity
        + 0.18 * color_similarity
        + 0.14 * region_balance
        + 0.11 * island_score
        + 0.06 * detail_preservation
    )

    return {
        "score": float(score),
        "edge_preservation_score": edge_preservation,
        "structural_similarity_score": structural_similarity,
        "color_similarity_score": color_similarity,
        "region_count": float(region_count),
        "tiny_islands": float(tiny_islands),
        "region_balance_score": float(region_balance),
        "island_score": float(island_score),
        "detail_preservation_score": float(detail_preservation),
    }


def _candidate_strengths(cfg: CartoonPreprocessConfig) -> list[tuple[str, int, float, float, int, int, int]]:
    base_iterations = max(1, int(cfg.rolling_guidance_iterations))
    base_spatial = float(cfg.rolling_guidance_spatial_sigma)
    base_range = float(cfg.rolling_guidance_range_sigma)
    base_mean_shift_spatial = max(1, int(cfg.mean_shift_spatial_radius))
    base_mean_shift_color = max(1, int(cfg.mean_shift_color_radius))
    base_poster_levels = max(6, int(round(cfg.stage1_colors / 5.0)))

    return [
        (
            "light",
            max(2, base_iterations - 2),
            max(4.0, base_spatial - 2.0),
            max(0.08, base_range - 0.02),
            max(6, base_mean_shift_spatial - 4),
            max(10, base_mean_shift_color - 6),
            max(10, base_poster_levels + 2),
        ),
        (
            "medium",
            max(4, base_iterations),
            max(5.0, base_spatial),
            max(0.10, base_range),
            max(8, base_mean_shift_spatial),
            max(12, base_mean_shift_color),
            max(8, base_poster_levels),
        ),
        (
            "strong",
            max(6, base_iterations + 2),
            min(8.0, base_spatial + 2.0),
            min(0.15, base_range + 0.03),
            max(10, base_mean_shift_spatial + 4),
            max(16, base_mean_shift_color + 6),
            max(6, base_poster_levels - 2),
        ),
    ]


def _run_candidate(
    original_rgb: np.ndarray,
    edge_map: np.ndarray,
    protected_edges: np.ndarray,
    semantic_masks: Any | None,
    iterations: int,
    spatial_sigma: float,
    range_sigma: float,
    mean_shift_spatial_radius: int,
    mean_shift_color_radius: int,
    poster_levels: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    smooth_weight = np.clip(0.16 + 0.94 * np.power(1.0 - _edge_density_map(edge_map), 1.35), 0.08, 1.0).astype(np.float32)

    detail_mask = _combine_masks(
        _extract_mask(semantic_masks, "face"),
        _extract_mask(semantic_masks, "hands"),
        _extract_mask(semantic_masks, "skin"),
        _extract_mask(semantic_masks, "hair"),
        _extract_mask(semantic_masks, "p1"),
    )
    background_mask = _extract_mask(semantic_masks, "background")

    if detail_mask is not None:
        detail_alpha = _feather_mask(detail_mask, radius=5)
        smooth_weight = np.where(detail_alpha > 0, np.minimum(smooth_weight, 0.28 + 0.12 * (1.0 - detail_alpha)), smooth_weight)
    if background_mask is not None:
        bg_alpha = _feather_mask(background_mask, radius=5)
        smooth_weight = np.where(bg_alpha > 0, np.maximum(smooth_weight, 0.82 + 0.18 * bg_alpha), smooth_weight)
    protected_alpha = _feather_mask(protected_edges, radius=3)
    smooth_weight = np.where(protected_alpha > 0, np.minimum(smooth_weight, 0.10 + 0.08 * (1.0 - protected_alpha)), smooth_weight)

    smoothed = _rolling_guidance_smooth(
        original_rgb,
        iterations=iterations,
        spatial_sigma=spatial_sigma,
        range_sigma=range_sigma,
        smooth_weight=smooth_weight,
    )
    mean_shifted = _adaptive_mean_shift(smoothed, mean_shift_spatial_radius, mean_shift_color_radius, semantic_masks)
    posterized = _posterize_rgb(mean_shifted, poster_levels)
    restored, lost_edges_mask = _restore_lost_structure(original_rgb, posterized, protected_edges, semantic_masks)
    metrics = _metric_signature(original_rgb, restored, edge_map, protected_edges, semantic_masks)

    metrics["rolling_guidance_iterations"] = float(iterations)
    metrics["rolling_guidance_spatial_sigma"] = float(spatial_sigma)
    metrics["rolling_guidance_range_sigma"] = float(range_sigma)
    metrics["mean_shift_spatial_radius"] = float(mean_shift_spatial_radius)
    metrics["mean_shift_color_radius"] = float(mean_shift_color_radius)
    metrics["poster_levels"] = float(poster_levels)
    return smoothed, restored, lost_edges_mask, metrics


def cartoon_preprocess(
    image_rgb: np.ndarray,
    cfg: CartoonPreprocessConfig,
    foreground_mask: np.ndarray | None = None,
    semantic_masks: Any | None = None,
    edge_strength: np.ndarray | None = None,
    protected_mask: np.ndarray | None = None,
) -> CartoonPreprocessResult:
    edge_map = _normalize01(edge_strength) if edge_strength is not None else _edge_map_from_rgb(image_rgb)
    protected_edges = _protected_edge_mask(edge_map, semantic_masks=semantic_masks, enabled=bool(cfg.edge_protection_enabled))
    if protected_mask is not None:
        protected_edges = cv2.max(protected_edges, np.asarray(protected_mask, dtype=np.uint8))

    if foreground_mask is not None:
        foreground_mask = np.asarray(foreground_mask, dtype=np.uint8)
        if foreground_mask.ndim == 2:
            protected_edges = cv2.max(protected_edges, foreground_mask)

    candidate_debug: dict[str, np.ndarray] = {
        "original": image_rgb.astype(np.uint8),
        "edge_map": np.clip(edge_map * 255.0, 0, 255).astype(np.uint8),
        "protected_edges": protected_edges.astype(np.uint8),
    }
    candidate_records: list[tuple[str, np.ndarray, np.ndarray, np.ndarray, dict[str, float]]] = []

    for name, iterations, spatial_sigma, range_sigma, mean_shift_spatial, mean_shift_color, poster_levels in _candidate_strengths(cfg):
        smoothed, restored, lost_edges_mask, metrics = _run_candidate(
            original_rgb=image_rgb,
            edge_map=edge_map,
            protected_edges=protected_edges,
            semantic_masks=semantic_masks,
            iterations=iterations,
            spatial_sigma=spatial_sigma,
            range_sigma=range_sigma,
            mean_shift_spatial_radius=mean_shift_spatial,
            mean_shift_color_radius=mean_shift_color,
            poster_levels=poster_levels,
        )
        candidate_records.append((name, smoothed, restored, lost_edges_mask, metrics))
        candidate_debug[f"smooth_{name}"] = restored.astype(np.uint8)

    selected_name, _, selected_rgb, selected_lost_edges_mask, selected_metrics = max(
        candidate_records,
        key=lambda item: item[4]["score"],
    )

    candidate_debug.setdefault("selected_cartoon_preprocess", selected_rgb.astype(np.uint8))
    candidate_debug.setdefault("restored_structure_preview", selected_rgb.astype(np.uint8))
    candidate_debug.setdefault("lost_edges_mask", selected_lost_edges_mask.astype(np.uint8))

    return CartoonPreprocessResult(
        selected_rgb=selected_rgb.astype(np.uint8),
        edge_map=edge_map.astype(np.float32),
        protected_edges=protected_edges.astype(np.uint8),
        selected_name=selected_name,
        selected_metrics=selected_metrics,
        debug_images={key: value.astype(np.uint8) for key, value in candidate_debug.items()},
    )
