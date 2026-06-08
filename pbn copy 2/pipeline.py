from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from .contour_extraction import RegionContour, extract_region_contours_adaptive
from .edges import build_edge_strength_map
from .exporters import (
    build_colored_preview,
    build_numbered_image,
    build_outline_image,
    ensure_dir,
    export_pdf,
    save_json,
    save_palette_json,
    save_png,
    save_svg,
)
from .image_loader import load_rgb_image
from .island_cleanup import cleanup_color_islands
from .number_placement import RegionNumber, place_region_numbers
from .palette_matching import (
    PaletteDataV2,
    assign_pixels_to_palette_semantic,
    build_palette_data,
    build_semantic_budgeted_palette_from_pixels,
    classify_pixels_by_semantics,
    quantize_image_lab,
)
from .pbn_config import PipelineConfigV2, default_palette_budget_for_mode
from .preprocessing import cartoon_preprocess, edge_preserving_smooth, resize_keep_aspect, rgb_to_lab
from .region_cleanup import RegionCleanupConfig, enforce_paintability, merge_tiny_components, smooth_region_shapes
from .semantic_regions import build_semantic_masks

logger = logging.getLogger(__name__)


def _mm_to_px(mm: float, dpi: int) -> float:
    return (float(mm) / 25.4) * float(dpi)


class PBNPipeline:
    def __init__(self, config: PipelineConfigV2) -> None:
        self.config = config

    def _validate_input(self, input_path: Path) -> None:
        if not input_path.exists() or not input_path.is_file():
            raise FileNotFoundError(f"Input image not found: {input_path}")

    def _mode_from_target_colors(self, n_colors: int) -> str:
        if n_colors <= 20:
            return "cheap"
        if n_colors <= 24:
            return "standard"
        return "detailed"

    def _build_region_stats(self, label_map: np.ndarray, numbers: list[RegionNumber], palette: PaletteDataV2) -> dict[str, object]:
        areas = np.array([n.area for n in numbers], dtype=np.float32)
        skipped = int(sum(1 for n in numbers if n.number_skipped))
        external = int(sum(1 for n in numbers if n.uses_external_label))
        return {
            "image_size": [int(label_map.shape[1]), int(label_map.shape[0])],
            "palette_size": int(len(palette.numbers)),
            "region_count": int(len(numbers)),
            "number_skipped_count": skipped,
            "external_label_count": external,
            "mean_region_area": float(areas.mean()) if areas.size else 0.0,
            "median_region_area": float(np.median(areas)) if areas.size else 0.0,
            "min_region_area": int(areas.min()) if areas.size else 0,
            "max_region_area": int(areas.max()) if areas.size else 0,
        }

    def run(self, input_path: Path, out_dir: Path) -> dict[str, object]:
        self._validate_input(input_path)
        ensure_dir(out_dir)

        logger.info("[1/10] Loading image")
        rgb = load_rgb_image(input_path)

        logger.info("[2/10] Resizing image")
        resized = resize_keep_aspect(rgb, self.config.target_longest_side)
        save_png(out_dir / "01_original.png", resized)

        logger.info("[3/10] Edge map + semantic masks")
        edge_strength = build_edge_strength_map(resized)
        sem = build_semantic_masks(resized, edge_strength=edge_strength, cfg=self.config.semantic)
        protected_mask = cv2.max(cv2.max(sem.p1, sem.face), sem.hands)
        importance_map = sem.foreground.astype(np.float32) / 255.0

        logger.info("[4/10] Edge-preserving smoothing")
        smooth = edge_preserving_smooth(resized, self.config.smoothing_strength)
        save_png(out_dir / "02_smoothed.png", smooth)

        logger.info("[5/10] Cartoon preprocessing")
        cartoon_result = cartoon_preprocess(
            smooth,
            cfg=self.config.cartoon,
            foreground_mask=importance_map,
            semantic_masks=sem,
            edge_strength=edge_strength,
            protected_mask=protected_mask,
        )
        cartoon_rgb = cartoon_result.selected_rgb
        save_png(out_dir / "03_cartoon_preprocessed.png", cartoon_rgb)
        save_png(out_dir / "original.png", resized)
        save_png(out_dir / "edge_map.png", (np.clip(cartoon_result.edge_map, 0.0, 1.0) * 255.0).astype(np.uint8))
        save_png(out_dir / "protected_edges.png", cartoon_result.protected_edges)
        save_png(out_dir / "smooth_light.png", cartoon_result.debug_images.get("smooth_light", cartoon_rgb))
        save_png(out_dir / "smooth_medium.png", cartoon_result.debug_images.get("smooth_medium", cartoon_rgb))
        save_png(out_dir / "smooth_strong.png", cartoon_result.debug_images.get("smooth_strong", cartoon_rgb))
        save_png(out_dir / "selected_cartoon_preprocess.png", cartoon_result.debug_images.get("selected_cartoon_preprocess", cartoon_rgb))
        save_png(out_dir / "lost_edges_mask.png", cartoon_result.debug_images.get("lost_edges_mask", np.zeros_like(edge_strength, dtype=np.uint8)))
        save_png(out_dir / "restored_structure_preview.png", cartoon_result.debug_images.get("restored_structure_preview", cartoon_rgb))

        logger.info("[6/10] Stage-A poster quantization")
        stage1_weights = 1.0 + 0.8 * importance_map + 0.9 * (protected_mask.astype(np.float32) / 255.0)
        _, _, _, stage1_poster_rgb = quantize_image_lab(
            cartoon_rgb,
            n_colors=int(self.config.cartoon.stage1_colors),
            weight_map=stage1_weights,
        )
        save_png(out_dir / "04_stage1_poster_50_colors.png", stage1_poster_rgb)

        logger.info("[7/10] Stage-B final quantization with semantic budget")
        masks = {
            "skin": cv2.max(sem.skin, cv2.max(sem.face, sem.hands)),
            "hair": sem.hair,
            "subject": cv2.max(sem.clothing, sem.person),
            "background": sem.background,
            "accents": sem.p1,
        }
        pixel_categories = classify_pixels_by_semantics(masks)

        if self.config.use_semantic_budgeting:
            mode = self._mode_from_target_colors(int(self.config.target_palette_size))
            budget = default_palette_budget_for_mode(mode)
            palette, palette_categories = build_semantic_budgeted_palette_from_pixels(
                image_rgb=stage1_poster_rgb,
                pixel_categories=pixel_categories,
                budget=budget,
                target_size=self.config.target_palette_size,
            )
            label_map_before = assign_pixels_to_palette_semantic(
                image_rgb=stage1_poster_rgb,
                palette_lab=palette.lab,
                pixel_categories=pixel_categories,
                palette_categories=palette_categories,
            )
        else:
            palette = build_palette_data(self.config.palette)
            lab_flat = cv2.cvtColor(stage1_poster_rgb, cv2.COLOR_RGB2LAB).astype(np.float32).reshape(-1, 3)
            p_lab = cv2.cvtColor(palette.rgb.reshape(1, -1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
            d = np.linalg.norm(lab_flat[:, None, :] - p_lab[None, :, :], axis=2)
            label_map_before = np.argmin(d, axis=1).reshape(stage1_poster_rgb.shape[:2]).astype(np.int32)

        before_preview = build_colored_preview(label_map_before, palette)
        save_png(out_dir / "05_final_24_colors_before_cleanup.png", before_preview)

        logger.info("[8/10] Surrounded island cleanup + large-area consistency")
        image_lab_stage1 = rgb_to_lab(stage1_poster_rgb)
        cleaned, island_cleanup_mask = cleanup_color_islands(
            label_map=label_map_before,
            palette_lab=palette.lab,
            image_lab=image_lab_stage1,
            cfg=self.config.island_cleanup,
            protected_mask=protected_mask,
            foreground_mask=sem.foreground,
            edge_strength=edge_strength,
        )
        save_png(out_dir / "06_island_cleanup_mask.png", np.repeat(island_cleanup_mask[:, :, None], 3, axis=2))

        cleanup_cfg = RegionCleanupConfig(
            min_region_area_px=self.config.min_region_area_px,
            min_region_area_percent=self.config.min_region_area_percent,
            min_region_width_px=max(2, int(round(_mm_to_px(self.config.min_paintable_diameter_mm, self.config.print_dpi)))),
            min_region_height_px=max(2, int(round(_mm_to_px(self.config.min_paintable_diameter_mm, self.config.print_dpi)))),
            min_number_radius_px=max(
                1.6,
                float(_mm_to_px(self.config.min_paintable_diameter_mm, self.config.print_dpi) * 0.5),
                float(_mm_to_px(self.config.number_font_size_mm, self.config.print_dpi) * 0.45),
            ),
            allow_external_labels=bool(self.config.allow_external_labels),
            max_external_labels_percent=float(self.config.max_external_labels_percent),
            shape_cleanup_passes=self.config.shape_cleanup_passes,
            edge_protection_percentile=self.config.edge_protection_percentile,
            protected_edge_dilate_px=self.config.protected_edge_dilate_px,
            detail_protection_strength=self.config.detail_protection_strength,
        )
        cleaned = merge_tiny_components(
            cleaned,
            image_lab_stage1,
            cleanup_cfg,
            edge_strength=edge_strength,
            importance_map=importance_map,
            protected_mask=protected_mask,
        )
        cleaned = enforce_paintability(
            cleaned,
            image_lab_stage1,
            cleanup_cfg,
            edge_strength=edge_strength,
            importance_map=importance_map,
            protected_mask=protected_mask,
        )
        cleaned = smooth_region_shapes(cleaned, cleanup_cfg.shape_cleanup_passes, protected_mask=protected_mask)
        final_preview = build_colored_preview(cleaned, palette)
        save_png(out_dir / "07_final_clean_pbn_preview.png", final_preview)

        logger.info("[9/10] Contour extraction + number placement")
        contours: list[RegionContour] = extract_region_contours_adaptive(
            cleaned,
            self.config.contour_simplify_tolerance,
            edge_strength=edge_strength,
            importance_map=importance_map,
            protected_mask=protected_mask,
        )
        numbers: list[RegionNumber] = place_region_numbers(
            cleaned,
            self.config.min_number_area_px,
            min_number_radius_px=cleanup_cfg.min_number_radius_px,
            allow_external_labels=self.config.allow_external_labels,
            max_external_labels_percent=self.config.max_external_labels_percent,
            protected_mask=protected_mask,
        )

        logger.info("[10/10] Rendering template + exports")
        h, w = cleaned.shape
        outline = build_outline_image((h, w), contours, self.config.line_width)
        numbered = build_numbered_image((h, w), contours, numbers, self.config.line_width, self.config.number_font_scale)

        colored_path = out_dir / "colored_preview.png"
        colored_debug_path = out_dir / "07_final_clean_pbn_preview.png"
        outline_path = out_dir / "pbn_outline.png"
        numbered_path = out_dir / "pbn_numbered.png"
        numbered_debug_path = out_dir / "08_numbered_template.png"
        svg_path = out_dir / "pbn_vector.svg"
        palette_path = out_dir / "palette.json"
        pdf_path = out_dir / "final_print.pdf"
        regions_path = out_dir / "regions.json"
        region_stats_path = out_dir / "region_stats.json"

        save_png(colored_path, final_preview)
        save_png(colored_debug_path, final_preview)
        save_png(out_dir / "final_pbn_preview.png", final_preview)
        save_png(outline_path, outline)
        save_png(numbered_path, numbered)
        save_png(numbered_debug_path, numbered)
        save_svg(svg_path, (h, w), contours, numbers, palette)
        save_palette_json(palette_path, palette)
        export_pdf(pdf_path, numbered_path, palette, self.config.page_size)

        regions_payload = [
            {
                "region_id": int(n.region_id),
                "color_number": int(n.color_label + 1),
                "area": int(n.area),
                "centroid": [float(round(n.centroid_xy[0], 3)), float(round(n.centroid_xy[1], 3))],
                "number_position": list(n.number_position_xy) if n.number_position_xy is not None else None,
                "number_skipped": bool(n.number_skipped),
                "uses_external_label": bool(n.uses_external_label),
                "leader_line_start": list(n.leader_line_start_xy) if n.leader_line_start_xy is not None else None,
                "leader_line_end": list(n.leader_line_end_xy) if n.leader_line_end_xy is not None else None,
            }
            for n in numbers
        ]
        save_json(regions_path, regions_payload)
        save_json(region_stats_path, self._build_region_stats(cleaned, numbers, palette))

        return {
            "colored_preview": str(colored_path),
            "original": str(out_dir / "01_original.png"),
            "smoothed": str(out_dir / "02_smoothed.png"),
            "cartoon_preprocessed": str(out_dir / "03_cartoon_preprocessed.png"),
            "original_debug": str(out_dir / "original.png"),
            "edge_map": str(out_dir / "edge_map.png"),
            "protected_edges": str(out_dir / "protected_edges.png"),
            "smooth_light": str(out_dir / "smooth_light.png"),
            "smooth_medium": str(out_dir / "smooth_medium.png"),
            "smooth_strong": str(out_dir / "smooth_strong.png"),
            "selected_cartoon_preprocess": str(out_dir / "selected_cartoon_preprocess.png"),
            "lost_edges_mask": str(out_dir / "lost_edges_mask.png"),
            "restored_structure_preview": str(out_dir / "restored_structure_preview.png"),
            "stage1_poster": str(out_dir / "04_stage1_poster_50_colors.png"),
            "final_before_cleanup": str(out_dir / "05_final_24_colors_before_cleanup.png"),
            "island_cleanup_mask": str(out_dir / "06_island_cleanup_mask.png"),
            "final_clean_pbn_preview": str(colored_debug_path),
            "final_pbn_preview": str(out_dir / "final_pbn_preview.png"),
            "pbn_outline": str(outline_path),
            "pbn_numbered": str(numbered_path),
            "numbered_template_debug": str(numbered_debug_path),
            "pbn_vector": str(svg_path),
            "palette_json": str(palette_path),
            "final_print_pdf": str(pdf_path),
            "regions_json": str(regions_path),
            "region_stats_json": str(region_stats_path),
        }
