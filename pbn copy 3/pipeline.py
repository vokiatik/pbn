from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from .contour_extraction import extract_region_contours_adaptive
from .edges import build_edge_strength_map
from .exporters import (
    build_colored_preview,
    build_numbered_image_from_labels,
    build_outline_image_from_labels,
    ensure_dir,
    export_pdf,
    save_json,
    save_palette_json,
    save_png,
    save_svg,
)
from .final_cleanup import FinalSimplifyConfig, simplify_final_regions
from .image_loader import load_rgb_image
from .number_placement import RegionNumber, place_region_numbers
from .palette_matching import PaletteDataV2, quantize_image_lab
from .pbn_config import SimplePipelineConfig
from .preprocessing import resize_keep_aspect, rgb_to_lab, smooth_image

logger = logging.getLogger(__name__)


def _mm_to_px(mm: float, dpi: int) -> float:
    return (float(mm) / 25.4) * float(dpi)


def _make_palette_from_centers(
    centers_lab: np.ndarray,
    centers_rgb: np.ndarray,
) -> PaletteDataV2:
    n = int(centers_lab.shape[0])
    numbers = np.arange(1, n + 1, dtype=np.int32)
    names = [f"Color {i:02d}" for i in range(1, n + 1)]
    hex_codes = [f"#{int(r):02X}{int(g):02X}{int(b):02X}" for r, g, b in centers_rgb.tolist()]
    return PaletteDataV2(
        numbers=numbers,
        names=names,
        hex_codes=hex_codes,
        rgb=centers_rgb,
        lab=centers_lab.astype(np.float32),
    )


def _count_regions(label_map: np.ndarray) -> int:
    total = 0
    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        n, _ = cv2.connectedComponents(mask, connectivity=8)
        total += n - 1
    return total


def _paintability_score(
    label_map: np.ndarray,
    min_area_px: int,
    min_radius_px: float,
) -> float:
    """Returns fraction of regions that have an inscribed circle large enough for a number."""
    total = 0
    valid = 0
    for color in np.unique(label_map):
        mask = (label_map == color).astype(np.uint8)
        n, cc, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            total += 1
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area >= min_area_px:
                comp = (cc == i).astype(np.uint8)
                dist = cv2.distanceTransform(comp, cv2.DIST_L2, 5)
                if float(dist.max()) >= min_radius_px:
                    valid += 1
    return float(valid) / max(1, total)


class PBNPipeline:
    """
    Simplified 7-stage paint-by-number pipeline.

    Stages:
      1. Load      - EXIF-corrected resize to working resolution.
      2. Smooth    - Single mean-shift (or bilateral) pass.
      3. Quantize  - Optional pre-quantize then final k-means.
      4. Cleanup   - One combined pass: tiny/unpaintable regions, holes, slivers.
      5. Outline   - Contour extraction + number placement.
      6. Render    - Colored preview + numbered template.
      7. Export    - 4 main outputs + SVG + region data.
                     Debug mode: also 6 intermediate images + stats.json.

    Default preset: fast_clean_24
    """

    def __init__(self, config: SimplePipelineConfig) -> None:
        self.config = config

    def _validate_input(self, input_path: Path) -> None:
        if not input_path.exists() or not input_path.is_file():
            raise FileNotFoundError(f"Input image not found: {input_path}")

    def run(self, input_path: Path, out_dir: Path) -> dict[str, object]:
        self._validate_input(input_path)
        ensure_dir(out_dir)

        cfg = self.config
        debug = bool(cfg.debug)
        t_total = time.perf_counter()
        stage_times: dict[str, float] = {}

        # ── Stage 1: Load ──────────────────────────────────────────────────────
        logger.info("[1/7] Loading image")
        t0 = time.perf_counter()
        rgb = load_rgb_image(input_path)
        resized = resize_keep_aspect(rgb, cfg.working_resolution_long_side)
        if debug:
            save_png(out_dir / "01_loaded.png", resized)
        stage_times["load_s"] = round(time.perf_counter() - t0, 3)
        logger.info(
            "  loaded %dx%d -> resized %dx%d",
            rgb.shape[1], rgb.shape[0],
            resized.shape[1], resized.shape[0],
        )

        # ── Stage 2: Smooth ────────────────────────────────────────────────────
        logger.info("[2/7] Smoothing (%s)", cfg.smoothing_method)
        t0 = time.perf_counter()
        smoothed = smooth_image(
            resized,
            method=cfg.smoothing_method,
            mean_shift_spatial_radius=cfg.mean_shift_spatial_radius,
            mean_shift_color_radius=cfg.mean_shift_color_radius,
            bilateral_sigma_color=cfg.bilateral_sigma_color,
            bilateral_sigma_space=cfg.bilateral_sigma_space,
        )
        if debug:
            save_png(out_dir / "01_preprocessed.png", smoothed)
        stage_times["smooth_s"] = round(time.perf_counter() - t0, 3)

        # Compute edge strength + importance map once — reused in Stages 3 and 4.
        # importance_weight biases k-means toward the visually interesting parts of the
        # image (subject, detail areas) so palette slots aren't wasted on flat backgrounds.
        edge_strength = build_edge_strength_map(resized)
        _h, _w = resized.shape[:2]
        _gy, _gx = np.mgrid[0:_h, 0:_w].astype(np.float32)
        _cy, _cx = _h / 2.0, _w / 2.0
        _sigma = min(_h, _w) * 0.38
        _center_w = np.exp(-((_gx - _cx) ** 2 + (_gy - _cy) ** 2) / (2.0 * _sigma ** 2))
        _blur_r = max(5, int(min(_h, _w) * 0.015)) | 1  # odd kernel
        _edge_density = cv2.GaussianBlur(edge_strength, (_blur_r, _blur_r), 0)
        _edge_density = _edge_density / (_edge_density.max() + 1e-6)
        # subjects tend to be centred; edges reveal detail — both deserve more palette colors
        importance_weight = (1.0 + 4.0 * (0.55 * _center_w + 0.45 * _edge_density)).astype(np.float32)
        if debug:
            _iw_u8 = np.clip(importance_weight / importance_weight.max() * 255, 0, 255).astype(np.uint8)
            save_png(out_dir / "02_importance_map.png", np.repeat(_iw_u8[:, :, None], 3, axis=2))

        # ── Stage 3: Quantize ──────────────────────────────────────────────────
        logger.info("[3/7] Quantizing colors (pre=%d -> final=%d)", cfg.pre_quantize_colors, cfg.final_colors)
        t0 = time.perf_counter()
        work_image = smoothed
        if cfg.pre_quantize_colors > 0:
            _, _, _, pre_quant = quantize_image_lab(work_image, cfg.pre_quantize_colors, weight_map=importance_weight)
            work_image = pre_quant
        labels, centers_lab, centers_rgb, quant_rgb = quantize_image_lab(work_image, cfg.final_colors, weight_map=importance_weight)
        palette = _make_palette_from_centers(centers_lab, centers_rgb)
        labels = labels.astype(np.int32)
        if debug:
            save_png(out_dir / "03_quantized.png", quant_rgb)
        stage_times["quantize_s"] = round(time.perf_counter() - t0, 3)

        # ── Stage 4: Region cleanup ────────────────────────────────────────────
        logger.info("[4/7] Region cleanup")
        t0 = time.perf_counter()
        # edge_strength already computed above
        image_lab = rgb_to_lab(smoothed)
        protected_mask = np.zeros(resized.shape[:2], dtype=np.uint8)
        region_count_before = _count_regions(labels)
        if debug:
            save_png(out_dir / "04_before_cleanup.png", build_colored_preview(labels, palette))

        cleanup_cfg = FinalSimplifyConfig(
            print_dpi=cfg.print_dpi,
            min_paintable_diameter_mm=cfg.min_paintable_diameter_mm,
            min_region_area_mm2=cfg.min_region_area_mm2,
            min_inscribed_circle_radius_mm=cfg.min_inscribed_circle_radius_mm,
            min_region_width_mm=cfg.min_region_width_mm,
            min_region_height_mm=cfg.min_region_height_mm,
            max_regions_per_cm2=cfg.max_regions_per_cm2,
            max_border_length_per_cm2=cfg.max_border_length_per_cm2,
            local_density_window_mm=cfg.local_density_window_mm,
            hole_fill_area_mm2=cfg.hole_fill_area_mm2,
            sliver_min_width_mm=cfg.sliver_min_width_mm,
            branch_min_width_mm=cfg.branch_min_width_mm,
            max_iterations=cfg.cleanup_max_iterations,
        )
        result = simplify_final_regions(
            label_map=labels,
            palette_lab=palette.lab,
            image_lab=image_lab,
            edge_strength=edge_strength,
            protected_mask=protected_mask,
            cfg=cleanup_cfg,
        )
        labels = result.label_map
        region_count_after = result.region_count_after

        if debug:
            save_png(out_dir / "04_after_cleanup.png", build_colored_preview(labels, palette))
            save_png(
                out_dir / "05_unpaintable_mask.png",
                np.repeat(result.unpaintable_regions_mask[:, :, None], 3, axis=2),
            )
        stage_times["cleanup_s"] = round(time.perf_counter() - t0, 3)
        logger.info(
            "  regions before=%d after=%d merged=%d",
            region_count_before,
            region_count_after,
            region_count_before - region_count_after,
        )

        # ── Stage 5: Outline + number placement ───────────────────────────────
        logger.info("[5/7] Outline and number placement")
        t0 = time.perf_counter()
        contour_tol_px = max(0.2, _mm_to_px(cfg.contour_simplification_mm, cfg.print_dpi))
        contours = extract_region_contours_adaptive(
            labels,
            contour_tol_px,
            edge_strength=edge_strength,
            importance_map=np.ones(resized.shape[:2], dtype=np.float32),
            protected_mask=protected_mask,
        )
        min_number_radius_px = max(
            1.6,
            float(_mm_to_px(cfg.min_paintable_diameter_mm, cfg.print_dpi) * 0.5),
            float(_mm_to_px(cfg.number_font_size_mm, cfg.print_dpi) * 0.45),
        )
        numbers: list[RegionNumber] = place_region_numbers(
            labels,
            cfg.min_number_area_px,
            min_number_radius_px=min_number_radius_px,
            allow_external_labels=cfg.allow_external_labels,
            max_external_labels_percent=cfg.max_external_labels_percent,
            protected_mask=protected_mask,
        )
        if debug:
            line_width_px = max(1, int(round(_mm_to_px(cfg.line_width_mm, cfg.print_dpi))))
            save_png(
                out_dir / "06_outline_preview.png",
                build_outline_image_from_labels(
                    labels, line_width=line_width_px, line_color_hex=cfg.line_color
                ),
            )
        stage_times["numbers_s"] = round(time.perf_counter() - t0, 3)

        # ── Stage 6: Render ───────────────────────────────────────────────────
        logger.info("[6/7] Rendering")
        t0 = time.perf_counter()
        h, w = labels.shape
        line_width_px = max(1, int(round(_mm_to_px(cfg.line_width_mm, cfg.print_dpi))))
        colored = build_colored_preview(labels, palette)
        numbered = build_numbered_image_from_labels(
            labels,
            numbers,
            line_width=line_width_px,
            font_scale=cfg.number_font_scale,
            line_color_hex=cfg.line_color,
        )
        stage_times["render_s"] = round(time.perf_counter() - t0, 3)

        # ── Stage 7: Export ───────────────────────────────────────────────────
        logger.info("[7/7] Exporting")
        t0 = time.perf_counter()

        colored_path = out_dir / "colored_preview.png"
        numbered_path = out_dir / "numbered_template.png"
        palette_path = out_dir / "palette.json"
        pdf_path = out_dir / "print.pdf"
        svg_path = out_dir / "pbn_vector.svg"
        regions_path = out_dir / "regions.json"
        region_stats_path = out_dir / "region_stats.json"

        save_png(colored_path, colored)
        save_png(numbered_path, numbered)
        save_palette_json(palette_path, palette)
        export_pdf(pdf_path, numbered_path, palette, cfg.page_size)
        save_svg(svg_path, (h, w), contours, numbers, palette)

        regions_payload = [
            {
                "region_id": int(n.region_id),
                "color_number": int(n.color_label + 1),
                "area": int(n.area),
                "centroid": [float(round(n.centroid_xy[0], 3)), float(round(n.centroid_xy[1], 3))],
                "number_position": list(n.number_position_xy) if n.number_position_xy is not None else None,
                "number_skipped": bool(n.number_skipped),
                "uses_external_label": bool(n.uses_external_label),
            }
            for n in numbers
        ]
        save_json(regions_path, regions_payload)

        region_areas = [int(n.area) for n in numbers]
        region_stats: dict[str, object] = {
            "image_size": [int(w), int(h)],
            "palette_size": int(len(palette.numbers)),
            "region_count": len(numbers),
            "number_skipped_count": int(sum(1 for n in numbers if n.number_skipped)),
            "external_label_count": int(sum(1 for n in numbers if n.uses_external_label)),
            "mean_region_area": float(np.mean(region_areas)) if region_areas else 0.0,
            "median_region_area": float(np.median(region_areas)) if region_areas else 0.0,
        }
        save_json(region_stats_path, region_stats)
        stage_times["export_s"] = round(time.perf_counter() - t0, 3)

        # ── Summary ───────────────────────────────────────────────────────────
        total_time = round(time.perf_counter() - t_total, 3)
        min_area_px = max(4, int(round(_mm_to_px(cfg.min_paintable_diameter_mm, cfg.print_dpi) ** 2 * 0.8)))
        min_radius_px = float(_mm_to_px(cfg.min_paintable_diameter_mm, cfg.print_dpi) * 0.5)
        p_score = _paintability_score(labels, min_area_px, min_radius_px)

        pipeline_stats: dict[str, object] = {
            "preset": cfg.preset,
            "region_count_before_cleanup": int(region_count_before),
            "region_count_after_cleanup": int(region_count_after),
            "regions_merged": int(region_count_before - region_count_after),
            "final_palette_size": int(len(palette.numbers)),
            "paintability_score": round(p_score, 4),
            "total_time_s": total_time,
            "stage_times": stage_times,
        }
        logger.info(
            "Pipeline done in %.1fs  regions %d -> %d  paintability %.2f",
            total_time,
            region_count_before,
            region_count_after,
            p_score,
        )
        for stage, secs in stage_times.items():
            pct = round(100.0 * secs / max(total_time, 0.001), 1)
            logger.info("  %-18s %.2fs  (%s%%)", stage, secs, pct)

        if debug:
            save_json(out_dir / "stats.json", pipeline_stats)

        return {
            "colored_preview": str(colored_path),
            "numbered_template": str(numbered_path),
            "palette_json": str(palette_path),
            "final_print_pdf": str(pdf_path),
            "pbn_vector": str(svg_path),
            "regions_json": str(regions_path),
            "region_stats_json": str(region_stats_path),
        }
