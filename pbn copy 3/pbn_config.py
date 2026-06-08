from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml


@dataclass(frozen=True)
class PaletteColor:
    number: int
    name: str
    hex: str


DEFAULT_PALETTE: list[PaletteColor] = [
    PaletteColor(1, "White", "#FFFFFF"),
    PaletteColor(2, "Black", "#000000"),
    PaletteColor(3, "Light Gray", "#D9D9D9"),
    PaletteColor(4, "Dark Gray", "#666666"),
    PaletteColor(5, "Red", "#D32F2F"),
    PaletteColor(6, "Pink", "#F48FB1"),
    PaletteColor(7, "Orange", "#F57C00"),
    PaletteColor(8, "Yellow", "#FBC02D"),
    PaletteColor(9, "Beige", "#D7B98E"),
    PaletteColor(10, "Brown", "#795548"),
    PaletteColor(11, "Light Green", "#A5D6A7"),
    PaletteColor(12, "Green", "#388E3C"),
    PaletteColor(13, "Dark Green", "#1B5E20"),
    PaletteColor(14, "Light Blue", "#90CAF9"),
    PaletteColor(15, "Blue", "#1976D2"),
    PaletteColor(16, "Dark Blue", "#0D47A1"),
    PaletteColor(17, "Purple", "#7B1FA2"),
    PaletteColor(18, "Violet", "#BA68C8"),
    PaletteColor(19, "Skin Light", "#F2C9A0"),
    PaletteColor(20, "Skin Dark", "#A66A45"),
]


LOW_COST_MODE_COLORS: dict[str, int] = {
    "cheap": 20,
    "standard": 24,
    "detailed": 30,
}

QUALITY_PRESET_CONFIG: dict[str, dict[str, float | int]] = {
    "low_cost_20": {
        "stage1_colors": 45,
        "final_colors": 20,
        "bilateral_iterations": 3,
        "mean_shift_spatial_radius": 12,
        "mean_shift_color_radius": 18,
        "min_island_area_percent": 0.0002,
        "surrounded_boundary_ratio": 0.70,
    },
    "balanced_24": {
        "stage1_colors": 55,
        "final_colors": 24,
        "bilateral_iterations": 3,
        "mean_shift_spatial_radius": 10,
        "mean_shift_color_radius": 16,
        "min_island_area_percent": 0.00015,
        "surrounded_boundary_ratio": 0.68,
    },
    "detailed_30": {
        "stage1_colors": 65,
        "final_colors": 30,
        "bilateral_iterations": 2,
        "mean_shift_spatial_radius": 8,
        "mean_shift_color_radius": 14,
        "min_island_area_percent": 0.0001,
        "surrounded_boundary_ratio": 0.65,
    },
    "clean_print_24": {
        "stage1_colors": 58,
        "final_colors": 24,
        "bilateral_iterations": 3,
        "mean_shift_spatial_radius": 10,
        "mean_shift_color_radius": 16,
        "min_island_area_percent": 0.00016,
        "surrounded_boundary_ratio": 0.70,
    },
    "extra_clean_20": {
        "stage1_colors": 52,
        "final_colors": 20,
        "bilateral_iterations": 3,
        "mean_shift_spatial_radius": 11,
        "mean_shift_color_radius": 18,
        "min_island_area_percent": 0.00022,
        "surrounded_boundary_ratio": 0.72,
    },
}


@dataclass
class SlicConfig:
    n_segments: int = 2500
    compactness: float = 20.0
    sigma: float = 1.0
    adaptive: bool = True
    edge_density_boost: float = 2.0
    protected_region_boost: float = 2.6
    protected_mask_dilate_px: int = 4


@dataclass
class SemanticConfig:
    enabled: bool = True
    external_mask_path: Path | None = None
    prefer_mediapipe: bool = True


@dataclass
class CartoonPreprocessConfig:
    bilateral_diameter: int = 9
    bilateral_sigma_color: float = 60.0
    bilateral_sigma_space: float = 60.0
    bilateral_iterations: int = 3
    mean_shift_spatial_radius: int = 10
    mean_shift_color_radius: int = 16
    stage1_colors: int = 55
    background_smoothing_boost: float = 1.25
    rolling_guidance_iterations: int = 4
    rolling_guidance_spatial_sigma: float = 6.0
    rolling_guidance_range_sigma: float = 0.11
    edge_protection_enabled: bool = True
    auto_search_enabled: bool = True


@dataclass
class IslandCleanupConfigV2:
    min_island_area_px: int = 180
    min_island_area_percent: float = 0.00015
    island_merge_delta_e: float = 22.0
    surrounded_boundary_ratio: float = 0.68
    max_iterations: int = 8
    background_area_multiplier: float = 1.5
    foreground_area_multiplier: float = 0.8
    protected_area_multiplier: float = 0.35


@dataclass
class PaletteBudgetConfig:
    skin_face_hands: int
    hair: int
    clothing_subject: int
    background: int
    accents: int


@dataclass
class PipelineConfigV2:
    palette: list[PaletteColor] = field(default_factory=lambda: DEFAULT_PALETTE.copy())
    low_cost_mode: str = "standard"
    target_palette_size: int = 24
    use_semantic_budgeting: bool = True
    semantic: SemanticConfig = field(default_factory=SemanticConfig)
    quality_preset: str = "balanced_24"
    cartoon: CartoonPreprocessConfig = field(default_factory=CartoonPreprocessConfig)
    island_cleanup: IslandCleanupConfigV2 = field(default_factory=IslandCleanupConfigV2)
    target_longest_side: int = 1800
    smoothing_strength: float = 1.0
    slic: SlicConfig = field(default_factory=SlicConfig)
    min_region_area_px: int = 28
    min_region_area_percent: float = 0.00008
    contour_simplify_tolerance: float = 0.85
    shape_cleanup_passes: int = 0
    edge_protection_percentile: float = 82.0
    protected_edge_dilate_px: int = 1
    detail_protection_strength: float = 1.0
    line_width: int = 1
    min_number_area_px: int = 90
    number_font_scale: float = 0.4
    min_paintable_diameter_mm: float = 4.0
    min_region_area_mm2: float = 20.0
    min_inscribed_circle_radius_mm: float = 2.5
    min_region_width_mm: float = 4.0
    min_region_height_mm: float = 4.0
    max_regions_per_cm2: float = 6.0
    max_border_length_per_cm2: float = 45.0
    local_density_window_mm: float = 15.0
    hole_fill_area_mm2: float = 10.0
    sliver_min_width_mm: float = 2.0
    branch_min_width_mm: float = 2.0
    final_cleanup_max_iterations: int = 28
    number_font_size_mm: float = 2.5
    print_dpi: int = 300
    line_width_mm: float = 0.2
    line_color: str = "#444444"
    contour_simplification_mm: float = 0.35
    smoothing_iterations: int = 1
    allow_external_labels: bool = True
    max_external_labels_percent: float = 3.0
    page_size: str = "a4"
    output_format: str = "png"
    max_workers: int = 4


@dataclass
class SimplePipelineConfig:
    """Simplified pipeline configuration. Default preset: fast_clean_24."""

    # Resolution
    working_resolution_long_side: int = 1800

    # Smoothing
    smoothing_method: str = "mean_shift"  # "mean_shift" or "bilateral"
    mean_shift_spatial_radius: int = 10
    mean_shift_color_radius: int = 16
    bilateral_sigma_color: float = 60.0
    bilateral_sigma_space: float = 12.0

    # Color quantization
    pre_quantize_colors: int = 40   # 0 = disabled
    final_colors: int = 24

    # Paintability thresholds (mm-based, DPI-independent)
    min_paintable_diameter_mm: float = 5.0
    min_region_area_mm2: float = 20.0
    min_inscribed_circle_radius_mm: float = 2.5
    min_region_width_mm: float = 4.0
    min_region_height_mm: float = 4.0
    max_regions_per_cm2: float = 6.0
    max_border_length_per_cm2: float = 45.0
    local_density_window_mm: float = 15.0
    hole_fill_area_mm2: float = 10.0
    sliver_min_width_mm: float = 2.0
    branch_min_width_mm: float = 2.0
    cleanup_max_iterations: int = 20

    # Output
    line_width_mm: float = 0.2
    line_color: str = "#444444"
    number_font_scale: float = 0.4
    number_font_size_mm: float = 2.5
    min_number_area_px: int = 90
    allow_external_labels: bool = True
    max_external_labels_percent: float = 3.0
    contour_simplification_mm: float = 0.35
    print_dpi: int = 300
    page_size: str = "a4"

    # Debug: when True, saves intermediate images and stats.json
    debug: bool = False
    preset: str = "fast_clean_24"


def make_fast_clean_24() -> SimplePipelineConfig:
    """Return the fast_clean_24 preset — the recommended default."""
    return SimplePipelineConfig(
        working_resolution_long_side=1800,
        smoothing_method="mean_shift",
        mean_shift_spatial_radius=10,
        mean_shift_color_radius=16,
        pre_quantize_colors=40,
        final_colors=24,
        min_paintable_diameter_mm=5.0,
        min_region_area_mm2=20.0,
        line_width_mm=0.2,
        debug=False,
        preset="fast_clean_24",
    )


def load_config(config_path: Path) -> "SimplePipelineConfig":
    """Load SimplePipelineConfig from a YAML file.

    Falls back to make_fast_clean_24() defaults for any missing key.
    Also accepts legacy field names (e.g. target_palette_size → final_colors).
    """
    if not config_path.exists():
        return make_fast_clean_24()

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError("Config root must be a YAML object")

    def _i(key: str, default: int, *aliases: str) -> int:
        for k in (key, *aliases):
            if k in raw:
                return max(1, int(raw[k]))
        return default

    def _f(key: str, default: float, *aliases: str) -> float:
        for k in (key, *aliases):
            if k in raw:
                return float(raw[k])
        return default

    def _s(key: str, default: str, *aliases: str) -> str:
        for k in (key, *aliases):
            if k in raw:
                return str(raw[k])
        return default

    def _b(key: str, default: bool) -> bool:
        if key in raw:
            return bool(raw[key])
        return default

    # Apply named preset overrides first, then let explicit keys override.
    preset = _s("preset", "fast_clean_24")
    base = make_fast_clean_24()
    preset_overrides: dict[str, object] = {}
    if preset in ("low_cost_20", "extra_clean_20"):
        preset_overrides = {"final_colors": 20, "mean_shift_spatial_radius": 12, "mean_shift_color_radius": 18}
    elif preset in ("detailed_30",):
        preset_overrides = {"final_colors": 30, "mean_shift_spatial_radius": 8, "mean_shift_color_radius": 14}

    def _override(key: str, raw_val: object) -> object:
        return raw_val if key in raw else preset_overrides.get(key, getattr(base, key))

    return SimplePipelineConfig(
        working_resolution_long_side=max(256, int(_override("working_resolution_long_side",
            raw.get("working_resolution_long_side", raw.get("target_image_size", base.working_resolution_long_side))))),
        smoothing_method=str(_override("smoothing_method", raw.get("smoothing_method", base.smoothing_method))),
        mean_shift_spatial_radius=max(1, int(_override("mean_shift_spatial_radius",
            raw.get("mean_shift_spatial_radius", base.mean_shift_spatial_radius)))),
        mean_shift_color_radius=max(1, int(_override("mean_shift_color_radius",
            raw.get("mean_shift_color_radius", base.mean_shift_color_radius)))),
        bilateral_sigma_color=max(1.0, float(raw.get("bilateral_sigma_color", base.bilateral_sigma_color))),
        bilateral_sigma_space=max(1.0, float(raw.get("bilateral_sigma_space", base.bilateral_sigma_space))),
        pre_quantize_colors=max(0, int(raw.get("pre_quantize_colors", base.pre_quantize_colors))),
        final_colors=max(20, min(32, int(_override("final_colors",
            raw.get("final_colors", raw.get("target_palette_size", base.final_colors)))))),
        min_paintable_diameter_mm=max(0.5, float(raw.get("min_paintable_diameter_mm", base.min_paintable_diameter_mm))),
        min_region_area_mm2=max(1.0, float(raw.get("min_region_area_mm2", base.min_region_area_mm2))),
        min_inscribed_circle_radius_mm=max(0.5, float(raw.get("min_inscribed_circle_radius_mm", base.min_inscribed_circle_radius_mm))),
        min_region_width_mm=max(0.5, float(raw.get("min_region_width_mm", base.min_region_width_mm))),
        min_region_height_mm=max(0.5, float(raw.get("min_region_height_mm", base.min_region_height_mm))),
        max_regions_per_cm2=max(0.1, float(raw.get("max_regions_per_cm2", base.max_regions_per_cm2))),
        max_border_length_per_cm2=max(1.0, float(raw.get("max_border_length_per_cm2", base.max_border_length_per_cm2))),
        local_density_window_mm=max(2.0, float(raw.get("local_density_window_mm", base.local_density_window_mm))),
        hole_fill_area_mm2=max(0.1, float(raw.get("hole_fill_area_mm2", base.hole_fill_area_mm2))),
        sliver_min_width_mm=max(0.5, float(raw.get("sliver_min_width_mm", base.sliver_min_width_mm))),
        branch_min_width_mm=max(0.5, float(raw.get("branch_min_width_mm", base.branch_min_width_mm))),
        cleanup_max_iterations=max(1, int(raw.get("cleanup_max_iterations",
            raw.get("final_cleanup_max_iterations", base.cleanup_max_iterations)))),
        line_width_mm=max(0.05, float(raw.get("line_width_mm", base.line_width_mm))),
        line_color=str(raw.get("line_color", base.line_color)),
        number_font_scale=max(0.1, float(raw.get("number_font_scale", base.number_font_scale))),
        number_font_size_mm=max(0.5, float(raw.get("number_font_size_mm", base.number_font_size_mm))),
        min_number_area_px=max(8, int(raw.get("min_number_area_px", base.min_number_area_px))),
        allow_external_labels=bool(raw.get("allow_external_labels", base.allow_external_labels)),
        max_external_labels_percent=float(raw.get("max_external_labels_percent", base.max_external_labels_percent)),
        contour_simplification_mm=max(0.05, float(raw.get("contour_simplification_mm", base.contour_simplification_mm))),
        print_dpi=max(72, int(raw.get("print_dpi", base.print_dpi))),
        page_size=str(raw.get("page_size", base.page_size)).lower(),
        debug=bool(raw.get("debug", base.debug)),
        preset=preset,
    )


def default_palette_budget_for_mode(mode: str) -> PaletteBudgetConfig:
    m = str(mode).strip().lower()
    if m == "cheap":
        return PaletteBudgetConfig(
            skin_face_hands=7,
            hair=3,
            clothing_subject=4,
            background=3,
            accents=3,
        )
    if m == "detailed":
        return PaletteBudgetConfig(
            skin_face_hands=10,
            hair=4,
            clothing_subject=6,
            background=5,
            accents=5,
        )
    return PaletteBudgetConfig(
        skin_face_hands=8,
        hair=3,
        clothing_subject=5,
        background=4,
        accents=4,
    )


