from __future__ import annotations

from pathlib import Path

import numpy as np

from .io_utils import atomic_write_json
from .models import RegionRecord, ValidationIssue, ValidationReport
from .print_spec import PrintSpec, mm_to_px
from .regions import build_adjacency
from .template_export import NumberingStats


def validate_template_inputs(
    region_map: np.ndarray,
    records: list[RegionRecord],
    region_to_color: dict[int, int],
    output_dir: Path,
    target_palette_size: int,
    print_spec: PrintSpec | None = None,
    region_budget: int | None = None,
    minimum_region_count: int | None = None,
    numbering_stats: NumberingStats | None = None,
    palette_rgb: list[tuple[int, int, int]] | None = None,
    painted_reference: np.ndarray | None = None,
    template_size: tuple[int, int] | None = None,
    min_area_mm2: float = 0.5,
    min_width_mm: float = 0.5,
    min_label_pocket_mm: float = 0.0,
    unnumbered_region_ids: list[int] | tuple[int, ...] | set[int] | None = None,
    prefilled_detail_region_ids: list[int] | tuple[int, ...] | set[int] | None = None,
    protected_region_ids: list[int] | tuple[int, ...] | set[int] | None = None,
    protected_boundary_retention: float | None = None,
    protected_mean_delta_e_00: float | None = None,
    protected_p90_delta_e_00: float | None = None,
    region_budget_multiplier: float = 1.10,
    maximum_prefilled_area_percent: float = 3.0,
    minimum_label_font_pt: float = 1.0 / 25.4 * 72.0,
    minimum_label_height_mm: float = 1.0,
    artificial_boundary_count: int | None = None,
    mean_reconstruction_delta_e_00: float | None = None,
    maximum_reconstruction_delta_e_00: float = 6.0,
) -> ValidationReport:
    print_spec = print_spec or PrintSpec()
    issues: list[ValidationIssue] = []
    active_region_ids = {int(value) for value in np.unique(region_map) if int(value)}
    record_by_id = {record.region_id: record for record in records}
    deliberate_dark_ids = set(numbering_stats.deliberate_dark_region_ids or []) if numbering_stats else set()
    prefilled_ids = set(numbering_stats.prefilled_detail_region_ids or []) if numbering_stats else set(prefilled_detail_region_ids or [])
    protected_ids = set(protected_region_ids or set())
    exempt_ids = deliberate_dark_ids | prefilled_ids | protected_ids
    unnumbered_ids = set(numbering_stats.unnumbered_region_ids if numbering_stats else (unnumbered_region_ids or []))

    if prefilled_ids - protected_ids:
        issues.append(
            ValidationIssue(
                "ordinary_region_prefilled",
                "fail",
                "only protected regions may use palette-colour label fallback",
            )
        )

    page_width, page_height = print_spec.page_px
    margin = mm_to_px(print_spec.margin_mm, print_spec.dpi)
    scale = min(
        (page_width - 2 * margin) / region_map.shape[1],
        (page_height - 2 * margin) / region_map.shape[0],
    )
    mm_per_source_pixel = scale * 25.4 / print_spec.dpi
    pixel_area_mm2 = mm_per_source_pixel**2
    areas_mm2: list[float] = []
    widths_mm: list[float] = []
    prefilled_area_mm2 = 0.0

    for region_id in sorted(active_region_ids):
        record = record_by_id.get(region_id)
        if record is None:
            issues.append(ValidationIssue("missing_region_record", "fail", "region id has no metadata", region_id))
            continue
        area_mm2 = record.area * pixel_area_mm2
        width_mm = record.estimated_thickness * mm_per_source_pixel
        areas_mm2.append(area_mm2)
        widths_mm.append(width_mm)
        if region_id in protected_ids:
            if area_mm2 + 1e-6 < 0.5:
                issues.append(ValidationIssue("protected_detail_too_small", "fail", "protected detail is below the 0.5 mm² printer floor", region_id))
            if width_mm + 1e-6 < 0.5:
                issues.append(ValidationIssue("protected_detail_too_thin", "fail", "protected detail is below the 0.5 mm printer floor", region_id))
        if region_id in prefilled_ids:
            prefilled_area_mm2 += area_mm2
            if area_mm2 + 1e-6 < 0.5:
                issues.append(ValidationIssue("prefilled_detail_too_small", "fail", "prefilled detail is below the 0.5 mm² printer floor", region_id))
            if width_mm + 1e-6 < 0.5:
                issues.append(ValidationIssue("prefilled_detail_too_thin", "fail", "prefilled detail is below the 0.5 mm printer floor", region_id))
        if region_id not in exempt_ids and area_mm2 + 1e-6 < min_area_mm2:
            issues.append(ValidationIssue("tiny_region", "fail", f"region area is {area_mm2:.2f} mm²; minimum is {min_area_mm2:g} mm²", region_id))
        if region_id not in exempt_ids and width_mm + 1e-6 < min_width_mm:
            issues.append(ValidationIssue("thin_region", "fail", f"region width is {width_mm:.2f} mm; minimum is {min_width_mm:g} mm", region_id))
        if region_id not in region_to_color:
            issues.append(ValidationIssue("unmapped_region", "fail", "region has no palette assignment", region_id))
        if region_id in unnumbered_ids and region_id not in exempt_ids:
            issues.append(ValidationIssue("unnumbered_region", "fail", "region has no readable internal number", region_id))

    mapped_region_ids = set(region_to_color)
    if mapped_region_ids != active_region_ids:
        issues.append(ValidationIssue("region_mapping_mismatch", "fail", "region map and palette mapping contain different region ids"))

    active_colors = {region_to_color[region_id] for region_id in active_region_ids if region_id in region_to_color}
    if any(color_id < 1 for color_id in active_colors):
        issues.append(ValidationIssue("invalid_palette_id", "fail", "palette ids must start at one"))
    if palette_rgb is not None and any(color_id > len(palette_rgb) for color_id in active_colors):
        issues.append(ValidationIssue("invalid_palette_id", "fail", "a region references a missing palette colour"))

    same_color_edges = _same_colour_adjacency_count(region_map, region_to_color)
    if same_color_edges:
        issues.append(ValidationIssue("same_color_adjacency", "fail", f"{same_color_edges} adjacent region pair(s) share a colour"))

    palette_size = len(active_colors)
    if palette_size > target_palette_size:
        issues.append(ValidationIssue("palette_over_target", "fail", "palette size exceeds requested target"))
    allowed_region_budget = int(np.ceil(region_budget * region_budget_multiplier)) if region_budget is not None else None
    if allowed_region_budget is not None and len(active_region_ids) > allowed_region_budget:
        issues.append(ValidationIssue("protected_budget_exceeded", "fail", f"region count exceeds protected overflow limit {allowed_region_budget}"))
    if minimum_region_count is not None and len(active_region_ids) < minimum_region_count:
        issues.append(ValidationIssue("region_count_below_difficulty", "fail", f"region count is below difficulty minimum {minimum_region_count}"))

    content_area_mm2 = max(1.0, region_map.size * pixel_area_mm2)
    prefilled_area_percent = 100.0 * prefilled_area_mm2 / content_area_mm2
    if prefilled_area_percent > maximum_prefilled_area_percent + 1e-6:
        issues.append(ValidationIssue("prefilled_area_exceeded", "fail", f"prefilled details cover {prefilled_area_percent:.2f}%; maximum is {maximum_prefilled_area_percent:g}%"))

    if numbering_stats and active_region_ids - prefilled_ids:
        if (
            numbering_stats.minimum_label_height_mm > 0.0
            and numbering_stats.minimum_label_height_mm + 1e-6 < minimum_label_height_mm
        ):
            issues.append(
                ValidationIssue(
                    "label_height_too_small",
                    "fail",
                    f"minimum printed label height is {numbering_stats.minimum_label_height_mm:.2f} mm; required is {minimum_label_height_mm:g} mm",
                )
            )
        if (
            numbering_stats.minimum_label_font_pt > 0.0
            and numbering_stats.minimum_label_font_pt + 1e-6 < minimum_label_font_pt
        ):
            issues.append(
                ValidationIssue(
                    "label_font_too_small",
                    "fail",
                    f"minimum label font is {numbering_stats.minimum_label_font_pt:.1f} pt; required is {minimum_label_font_pt:g} pt",
                )
            )

    if artificial_boundary_count is not None and artificial_boundary_count > 0:
        issues.append(
            ValidationIssue(
                "artificial_boundary",
                "fail",
                f"{artificial_boundary_count} unprotected weak boundary pair(s) use exaggerated paint contrast",
            )
        )
    if (
        mean_reconstruction_delta_e_00 is not None
        and mean_reconstruction_delta_e_00 > maximum_reconstruction_delta_e_00 + 1e-6
    ):
        issues.append(
            ValidationIssue(
                "global_reconstruction_loss",
                "fail",
                f"mean reconstruction delta E is {mean_reconstruction_delta_e_00:.2f}; maximum is {maximum_reconstruction_delta_e_00:g}",
            )
        )

    if protected_boundary_retention is not None and protected_boundary_retention + 1e-6 < 0.90:
        issues.append(ValidationIssue("protected_boundary_loss", "fail", f"protected boundary recall is {protected_boundary_retention:.3f}; minimum is 0.900"))
    if protected_mean_delta_e_00 is not None and protected_mean_delta_e_00 > 8.0 + 1e-6:
        issues.append(ValidationIssue("protected_colour_mean_loss", "fail", f"protected mean ΔE00 is {protected_mean_delta_e_00:.2f}; maximum is 8"))
    if protected_p90_delta_e_00 is not None and protected_p90_delta_e_00 > 15.0 + 1e-6:
        issues.append(ValidationIssue("protected_colour_p90_loss", "fail", f"protected p90 ΔE00 is {protected_p90_delta_e_00:.2f}; maximum is 15"))

    consistency_failures = 0
    if painted_reference is not None and palette_rgb is not None:
        expected_lut = np.full((int(region_map.max()) + 1, 3), 255, dtype=np.uint8)
        for region_id, color_id in region_to_color.items():
            if 1 <= color_id <= len(palette_rgb):
                expected_lut[region_id] = palette_rgb[color_id - 1]
        expected = expected_lut[region_map]
        consistency_failures = int(np.count_nonzero(np.any(expected != painted_reference, axis=2)))
        if consistency_failures:
            issues.append(ValidationIssue("painted_reference_mismatch", "fail", "painted reference does not match region mapping and palette"))

    expected_size = print_spec.page_px
    if template_size is not None and tuple(template_size) != expected_size:
        issues.append(ValidationIssue("page_size_mismatch", "fail", "template dimensions do not match the selected A-series page"))

    report = ValidationReport(
        status="fail" if issues else "pass",
        metrics={
            "total_region_count": len(active_region_ids),
            "region_budget": region_budget,
            "allowed_region_budget": allowed_region_budget,
            "region_budget_overflow_percent": (
                max(0.0, 100.0 * (len(active_region_ids) - region_budget) / max(1, region_budget))
                if region_budget is not None
                else 0.0
            ),
            "palette_size": palette_size,
            "target_palette_size": target_palette_size,
            "unmapped_region_count": len(active_region_ids - mapped_region_ids),
            "same_color_adjacency_count": same_color_edges,
            "unnumbered_region_count": len(unnumbered_ids - exempt_ids),
            "deliberate_dark_mark_count": len(deliberate_dark_ids),
            "prefilled_detail_count": len(prefilled_ids),
            "prefilled_area_percent": prefilled_area_percent,
            "adaptive_label_count": len(numbering_stats.adaptive_label_region_ids or []) if numbering_stats else 0,
            "minimum_label_font_pt": numbering_stats.minimum_label_font_pt if numbering_stats else 0.0,
            "minimum_label_height_mm": numbering_stats.minimum_label_height_mm if numbering_stats else 0.0,
            "label_height_counts": numbering_stats.label_height_counts if numbering_stats else {},
            "min_region_area_mm2": min(areas_mm2, default=0.0),
            "min_estimated_width_mm": min(widths_mm, default=0.0),
            "min_label_pocket_mm": numbering_stats.minimum_label_pocket_mm if numbering_stats else 0.0,
            "painted_reference_mismatch_pixels": consistency_failures,
            "page_size_px": list(expected_size),
            "safe_margin_mm": print_spec.margin_mm,
            "second_crop_count": 0,
            "protected_region_count": len(protected_ids),
            "protected_boundary_retention": protected_boundary_retention if protected_boundary_retention is not None else 1.0,
            "protected_mean_delta_e_00": protected_mean_delta_e_00 if protected_mean_delta_e_00 is not None else 0.0,
            "protected_p90_delta_e_00": protected_p90_delta_e_00 if protected_p90_delta_e_00 is not None else 0.0,
            "artificial_boundary_count": artificial_boundary_count if artificial_boundary_count is not None else 0,
            "mean_reconstruction_delta_e_00": mean_reconstruction_delta_e_00 if mean_reconstruction_delta_e_00 is not None else 0.0,
        },
        issues=issues,
        suggested_actions=_suggested_actions(issues),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "report.json", report.to_dict())
    return report


def _same_colour_adjacency_count(region_map: np.ndarray, region_to_color: dict[int, int]) -> int:
    count = 0
    for region_id, neighbours in build_adjacency(region_map).items():
        for neighbour in neighbours:
            if neighbour > region_id and region_to_color.get(region_id) == region_to_color.get(neighbour):
                count += 1
    return count


def _suggested_actions(issues: list[ValidationIssue]) -> list[str]:
    codes = {issue.code for issue in issues}
    actions: list[str] = []
    if codes & {"tiny_region", "thin_region", "label_pocket_too_small", "region_budget_exceeded", "protected_budget_exceeded"}:
        actions.append("Regenerate the AI image with larger colour areas and less fur, texture, or background detail.")
    if "unnumbered_region" in codes:
        actions.append("Regenerate with broader closed regions so every ordinary region can hold at least a 3 pt number.")
    if codes & {"same_color_adjacency", "painted_reference_mismatch", "region_mapping_mismatch", "ordinary_region_prefilled"}:
        actions.append("The local conversion was internally inconsistent; inspect the retry log before rerunning.")
    if "palette_over_target" in codes:
        actions.append("Use fewer distinct AI colour families or request a larger target palette.")
    if codes & {"protected_boundary_loss", "protected_colour_mean_loss", "protected_colour_p90_loss"}:
        actions.append("Regenerate with broader subject-defining colour regions or use a larger target palette.")
    return actions
