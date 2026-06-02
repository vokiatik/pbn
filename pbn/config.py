from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np


QUALITY_PRESETS: dict[str, dict] = {
    "low":    {"superpixel_area_px": 640,  "superpixels_min": 6000,  "superpixels_max": 20000},
    "medium": {"superpixel_area_px": 320,  "superpixels_min": 12000, "superpixels_max": 40000},
    "high":   {"superpixel_area_px": 160,  "superpixels_min": 20000, "superpixels_max": 60000},
}


@dataclass
class PipelineConfig:
    input_path: Path
    out_dir: Path
    colors: int = 32
    size: int = 2200
    min_region_area: int | None = 24
    superpixel_area_px: int = 320
    superpixel_shape: str = "adaptive"
    superpixels_min: int = 12000
    superpixels_max: int = 40000
    detail_level: float = 1.0
    edge_threshold: float = 0.14
    lab_merge_threshold: float = 16.0
    merge_iterations: int = 12
    line_width: int = 1
    min_number_area: int | None = None
    cleanup_passes: int = 0
    export_pdf: bool = False
    seed: int = 42
    importance_mask_path: Path | None = None
    preserve_detail_regions: bool = True
    line_color: tuple[int, int, int] = (80, 80, 80)
    print_format: str = "a4"

    def resolve_default_min_region_area(self, width: int, height: int) -> int:
        if self.min_region_area is not None:
            return int(self.min_region_area)
        base = max(12, int(round((width * height) / 220000.0)))
        scale = 1.25 - 0.55 * float(np.clip(self.detail_level, 0.0, 1.0))
        return max(6, int(round(base * scale)))

    def resolve_default_min_number_area(self, min_region_area_px: int) -> int:
        if self.min_number_area is not None:
            return int(self.min_number_area)
        scale = 0.52 - 0.24 * float(np.clip(self.detail_level, 0.0, 1.0))
        return max(14, int(round(min_region_area_px * scale)))


def parse_args() -> PipelineConfig:
    parser = argparse.ArgumentParser(
        description="Convert a realistic photo into a paint-by-number template"
    )
    parser.add_argument("input", type=Path, help="Input image path")
    parser.add_argument("--out", type=Path, default=Path("output"), help="Output folder")
    parser.add_argument("--colors", type=int, default=32, help="Target palette size")
    parser.add_argument("--size", type=int, default=2200, help="Longest output side in pixels")
    parser.add_argument(
        "--quality",
        type=str,
        choices=["low", "medium", "high"],
        default="medium",
        help=(
            "Superpixel quality preset. "
            "low=larger superpixels (faster, simpler), "
            "medium=default balanced, "
            "high=smaller superpixels (more detail, slower)"
        ),
    )
    parser.add_argument(
        "--detail-level",
        type=float,
        default=1.0,
        help="Detail preservation strength (0.0=more simplified, 1.0=more detailed)",
    )
    parser.add_argument(
        "--min-region-area",
        type=int,
        default=24,
        help="Minimum paintable region area in px (default: 24)",
    )
    parser.add_argument(
        "--superpixel-area-px",
        type=int,
        default=None,
        help="Override superpixel area in px (overrides --quality preset)",
    )
    parser.add_argument(
        "--superpixel-shape",
        type=str,
        choices=["square", "adaptive", "very-adaptive"],
        default="adaptive",
        help="Superpixel shape behavior: square (compact), adaptive (edge-following), very-adaptive (strong edge-following)",
    )
    parser.add_argument("--edge-threshold", type=float, default=0.14, help="Edge-safe merge threshold")
    parser.add_argument("--lab-merge-threshold", type=float, default=16.0, help="LAB distance threshold for merges")
    parser.add_argument("--merge-iterations", type=int, default=12, help="Maximum merge iterations")
    parser.add_argument("--line-width", type=int, default=1, help="Border line thickness")
    parser.add_argument("--min-number-area", type=int, default=None, help="Minimum region area for number placement")
    parser.add_argument("--cleanup-passes", type=int, default=0, help="Morphological cleanup passes")
    parser.add_argument(
        "--superpixels-min",
        type=int,
        default=None,
        help="Override lower bound for superpixel count (overrides --quality preset)",
    )
    parser.add_argument(
        "--superpixels-max",
        type=int,
        default=None,
        help="Override upper bound for superpixel count (overrides --quality preset)",
    )
    parser.add_argument("--importance-mask", type=Path, default=None, help="Optional external importance mask image")
    parser.add_argument(
        "--preserve-detail-regions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Strongly protect high-importance regions from merges",
    )
    parser.add_argument(
        "--line-color",
        type=str,
        default="80,80,80",
        help="RGB color for boundary lines and numbers, e.g. '80,80,80' for grey or '0,0,0' for black",
    )
    parser.add_argument(
        "--print-format",
        type=str,
        choices=["a4", "a3"],
        default="a4",
        help="Paper format for PDF export with 3 mm bleed: a4 or a3",
    )
    parser.add_argument("--pdf", action="store_true", help="Export optional PDF")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # Apply quality preset, then let explicit overrides win
    preset = QUALITY_PRESETS[args.quality]
    superpixel_area_px = args.superpixel_area_px if args.superpixel_area_px is not None else preset["superpixel_area_px"]
    superpixels_min_raw = args.superpixels_min if args.superpixels_min is not None else preset["superpixels_min"]
    superpixels_max_raw = args.superpixels_max if args.superpixels_max is not None else preset["superpixels_max"]
    superpixels_min = max(500, superpixels_min_raw)
    superpixels_max = max(superpixels_min, superpixels_max_raw)

    try:
        r, g, b = (int(v.strip()) for v in args.line_color.split(","))
        line_color: tuple[int, int, int] = (
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)),
        )
    except Exception:
        line_color = (80, 80, 80)

    return PipelineConfig(
        input_path=args.input,
        out_dir=args.out,
        colors=max(2, args.colors),
        size=max(256, args.size),
        min_region_area=args.min_region_area,
        superpixel_area_px=max(64, superpixel_area_px),
        superpixel_shape=args.superpixel_shape,
        superpixels_min=superpixels_min,
        superpixels_max=superpixels_max,
        detail_level=max(0.0, min(1.0, args.detail_level)),
        edge_threshold=max(0.0, min(1.0, args.edge_threshold)),
        lab_merge_threshold=max(1.0, args.lab_merge_threshold),
        merge_iterations=max(1, args.merge_iterations),
        line_width=max(1, args.line_width),
        min_number_area=args.min_number_area,
        cleanup_passes=max(0, args.cleanup_passes),
        export_pdf=args.pdf,
        seed=args.seed,
        importance_mask_path=args.importance_mask,
        preserve_detail_regions=bool(args.preserve_detail_regions),
        line_color=line_color,
        print_format=args.print_format,
    )
