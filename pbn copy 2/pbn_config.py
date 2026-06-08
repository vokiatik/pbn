from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    number_font_size_mm: float = 2.5
    print_dpi: int = 300
    allow_external_labels: bool = True
    max_external_labels_percent: float = 3.0
    page_size: str = "a4"
    output_format: str = "png"
    max_workers: int = 4


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


def _parse_palette(raw_palette: Any) -> list[PaletteColor]:
    if not isinstance(raw_palette, list) or len(raw_palette) < 2:
        raise ValueError("Palette must contain at least 2 colors")

    palette: list[PaletteColor] = []
    for item in raw_palette:
        if not isinstance(item, dict):
            raise ValueError("Each palette item must be an object")
        palette.append(
            PaletteColor(
                number=int(item["number"]),
                name=str(item["name"]),
                hex=str(item["hex"]).upper(),
            )
        )

    palette.sort(key=lambda c: c.number)
    expected = list(range(1, len(palette) + 1))
    got = [c.number for c in palette]
    if got != expected:
        raise ValueError("Palette numbers must be sequential starting at 1")
    return palette


def _parse_mode(raw_mode: Any) -> str:
    mode = str(raw_mode or "standard").strip().lower()
    if mode not in LOW_COST_MODE_COLORS:
        return "standard"
    return mode


def _parse_quality_preset(raw_preset: Any) -> str:
    preset = str(raw_preset or "balanced_24").strip().lower()
    if preset not in QUALITY_PRESET_CONFIG:
        return "balanced_24"
    return preset


def _mm_to_px(mm: float, dpi: int) -> float:
    return (float(mm) / 25.4) * float(dpi)


def load_config(config_path: Path) -> PipelineConfigV2:
    if not config_path.exists():
        return PipelineConfigV2()

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError("Config root must be a YAML object")

    mode = _parse_mode(raw.get("low_cost_mode", "standard"))
    preset = _parse_quality_preset(raw.get("quality_preset", "balanced_24"))
    preset_cfg = QUALITY_PRESET_CONFIG[preset]
    target_palette_size = max(
        20,
        min(30, int(raw.get("target_palette_size", int(preset_cfg["final_colors"])))),
    )

    palette_raw = raw.get("palette", [asdict(c) for c in DEFAULT_PALETTE])
    palette = _parse_palette(palette_raw)

    slic_raw = raw.get("slic", {}) or {}
    if not isinstance(slic_raw, dict):
        raise ValueError("slic config must be an object")

    semantic_raw = raw.get("semantic", {}) or {}
    if not isinstance(semantic_raw, dict):
        raise ValueError("semantic config must be an object")

    external_mask_raw = semantic_raw.get("external_mask_path")
    external_mask_path = None if external_mask_raw in (None, "") else Path(str(external_mask_raw))

    cartoon_raw = raw.get("cartoon_preprocess", {}) or {}
    if not isinstance(cartoon_raw, dict):
        raise ValueError("cartoon_preprocess config must be an object")

    island_raw = raw.get("island_cleanup", {}) or {}
    if not isinstance(island_raw, dict):
        raise ValueError("island_cleanup config must be an object")

    cfg = PipelineConfigV2(
        palette=palette,
        low_cost_mode=mode,
        target_palette_size=target_palette_size,
        use_semantic_budgeting=bool(raw.get("use_semantic_budgeting", True)),
        semantic=SemanticConfig(
            enabled=bool(semantic_raw.get("enabled", True)),
            external_mask_path=external_mask_path,
            prefer_mediapipe=bool(semantic_raw.get("prefer_mediapipe", True)),
        ),
        quality_preset=preset,
        cartoon=CartoonPreprocessConfig(
            bilateral_diameter=max(3, int(cartoon_raw.get("bilateral_diameter", 9))),
            bilateral_sigma_color=max(1.0, float(cartoon_raw.get("bilateral_sigma_color", 60.0))),
            bilateral_sigma_space=max(1.0, float(cartoon_raw.get("bilateral_sigma_space", 60.0))),
            bilateral_iterations=max(1, int(cartoon_raw.get("bilateral_iterations", int(preset_cfg["bilateral_iterations"])))),
            mean_shift_spatial_radius=max(1, int(cartoon_raw.get("mean_shift_spatial_radius", int(preset_cfg["mean_shift_spatial_radius"])))),
            mean_shift_color_radius=max(1, int(cartoon_raw.get("mean_shift_color_radius", int(preset_cfg["mean_shift_color_radius"])))),
            stage1_colors=max(30, min(90, int(cartoon_raw.get("stage1_colors", int(preset_cfg["stage1_colors"]))))),
            background_smoothing_boost=max(1.0, float(cartoon_raw.get("background_smoothing_boost", 1.25))),
            rolling_guidance_iterations=max(1, int(cartoon_raw.get("rolling_guidance_iterations", 4))),
            rolling_guidance_spatial_sigma=max(1.0, float(cartoon_raw.get("rolling_guidance_spatial_sigma", 6.0))),
            rolling_guidance_range_sigma=max(0.01, float(cartoon_raw.get("rolling_guidance_range_sigma", 0.11))),
            edge_protection_enabled=bool(cartoon_raw.get("edge_protection_enabled", True)),
            auto_search_enabled=bool(cartoon_raw.get("auto_search_enabled", True)),
        ),
        island_cleanup=IslandCleanupConfigV2(
            min_island_area_px=max(20, int(island_raw.get("min_island_area_px", 180))),
            min_island_area_percent=max(0.0, float(island_raw.get("min_island_area_percent", float(preset_cfg["min_island_area_percent"])))),
            island_merge_delta_e=max(2.0, float(island_raw.get("island_merge_delta_e", 22.0))),
            surrounded_boundary_ratio=float(
                max(0.5, min(0.95, float(island_raw.get("surrounded_boundary_ratio", float(preset_cfg["surrounded_boundary_ratio"]))))),
            ),
            max_iterations=max(1, int(island_raw.get("max_iterations", 8))),
            background_area_multiplier=max(1.0, float(island_raw.get("background_area_multiplier", 1.5))),
            foreground_area_multiplier=max(0.1, float(island_raw.get("foreground_area_multiplier", 0.8))),
            protected_area_multiplier=max(0.05, float(island_raw.get("protected_area_multiplier", 0.35))),
        ),
        target_longest_side=max(256, int(raw.get("target_image_size", 1800))),
        smoothing_strength=float(raw.get("smoothing_strength", 1.0)),
        slic=SlicConfig(
            n_segments=max(100, int(slic_raw.get("n_segments", 2500))),
            compactness=max(0.1, float(slic_raw.get("compactness", 20.0))),
            sigma=max(0.0, float(slic_raw.get("sigma", 1.0))),
            adaptive=bool(slic_raw.get("adaptive", True)),
            edge_density_boost=max(0.1, float(slic_raw.get("edge_density_boost", 2.0))),
            protected_region_boost=max(0.1, float(slic_raw.get("protected_region_boost", 2.6))),
            protected_mask_dilate_px=max(0, int(slic_raw.get("protected_mask_dilate_px", 4))),
        ),
        min_region_area_px=max(2, int(raw.get("min_region_area_px", 28))),
        min_region_area_percent=max(0.0, float(raw.get("min_region_area_percent", 0.00008))),
        contour_simplify_tolerance=max(0.05, float(raw.get("contour_simplification_tolerance", 0.85))),
        shape_cleanup_passes=max(0, int(raw.get("shape_cleanup_passes", 0))),
        edge_protection_percentile=float(max(45.0, min(99.5, float(raw.get("edge_protection_percentile", 82.0))))),
        protected_edge_dilate_px=max(0, int(raw.get("protected_edge_dilate_px", 1))),
        detail_protection_strength=max(0.0, float(raw.get("detail_protection_strength", 1.0))),
        line_width=max(1, int(raw.get("line_width", 1))),
        min_number_area_px=max(8, int(raw.get("min_number_area_px", 90))),
        number_font_scale=max(0.1, float(raw.get("number_font_scale", 0.4))),
        min_paintable_diameter_mm=max(0.5, float(raw.get("min_paintable_diameter_mm", 4.0))),
        number_font_size_mm=max(0.5, float(raw.get("number_font_size_mm", 2.5))),
        print_dpi=max(72, int(raw.get("print_dpi", 300))),
        allow_external_labels=bool(raw.get("allow_external_labels", True)),
        max_external_labels_percent=float(max(0.0, min(100.0, float(raw.get("max_external_labels_percent", 3.0))))),
        page_size=str(raw.get("page_size", "a4")).lower(),
        output_format=str(raw.get("output_format", "png")),
        max_workers=max(1, int(raw.get("max_workers", 4))),
    )

    min_diameter_px = _mm_to_px(cfg.min_paintable_diameter_mm, cfg.print_dpi)
    derived_min_area = int(round(np.pi * ((min_diameter_px * 0.5) ** 2)))
    cfg.min_region_area_px = max(int(cfg.min_region_area_px), max(8, derived_min_area))
    cfg.min_number_area_px = max(int(cfg.min_number_area_px), max(8, derived_min_area))
    return cfg
