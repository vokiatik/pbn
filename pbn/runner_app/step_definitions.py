from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from runner_app.config import SAM2_CHECKPOINT, SAM2_MODEL_CFG
from runner_app.utils import as_bool, require_file

from steps.step1_sam_objects import run_step1_sam_objects
from steps.step2_smooth_segments import run_step2_smooth_segments
from steps.step3_global_palette import run_step3_global_palette

# New split steps
from steps.step4_raw_regions import run_step4_raw_regions
from steps.step5_border_cleanup import run_step5_border_cleanup
from steps.step6_island_cleanup import run_step6_island_cleanup

# Existing old functions, now used as visible Step 7 and Step 8
from steps.step7_make_template import run_step7_make_template
from steps.step8_export_pdf import run_step8_export_pdf


StepRunner = Callable[[Path, Path, dict[str, Any]], tuple[Path, dict[str, Any]]]


@dataclass(frozen=True)
class StepDefinition:
    step: int
    title: str
    output_dir_name: str
    runner: StepRunner


def run_step_1(
    project_dir: Path,
    original_image: Path,
    params: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    output_dir = project_dir / "step1_objects"

    result = run_step1_sam_objects(
        image_path=str(original_image),
        output_dir=str(output_dir),
        checkpoint=params.get("checkpoint", SAM2_CHECKPOINT),
        model_cfg=params.get("model_cfg", SAM2_MODEL_CFG),
        points_per_side=int(params.get("points_per_side", 32)),
        pred_iou_thresh=float(params.get("pred_iou_thresh", 0.88)),
        stability_score_thresh=float(params.get("stability_score_thresh", 0.92)),
        min_mask_region_area=int(params.get("min_mask_region_area", 400)),
        min_area_ratio=float(params.get("min_area_ratio", 0.002)),
        max_area_ratio=float(params.get("max_area_ratio", 0.80)),
        dedupe_iou=float(params.get("dedupe_iou", 0.92)),
    )

    return output_dir, result


def run_step_2(
    project_dir: Path,
    original_image: Path,
    params: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    output_dir = project_dir / "step2_smooth"
    metadata_path = project_dir / "step1_objects" / "metadata.json"

    result = run_step2_smooth_segments(
        image_path=str(original_image),
        metadata_path=require_file(metadata_path, "step 1 metadata"),
        output_dir=str(output_dir),
        colors_per_object=int(params.get("colors_per_object", 5)),
        background_colors=int(params.get("background_colors", 6)),
        min_region_area=int(params.get("min_region_area", 300)),
        process_background=as_bool(params.get("process_background"), default=True),
        max_objects=int(params.get("max_objects", 80)),
    )

    return output_dir, result


def run_step_3(
    project_dir: Path,
    original_image: Path,
    params: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    output_dir = project_dir / "step3_palette"
    step2_image = project_dir / "step2_smooth" / "step2_smoothed.png"

    result = run_step3_global_palette(
        image_path=require_file(step2_image, "step 2 smoothed image"),
        output_dir=str(output_dir),
        palette_size=int(params.get("palette_size", 30)),
    )

    return output_dir, result


def run_step_4(
    project_dir: Path,
    original_image: Path,
    params: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """
    Step 4: raw regions.

    This step creates a stable raw baseline from Step 3 label_map.
    No border smoothing.
    No island cleanup.
    """
    output_dir = project_dir / "step4_raw_regions"
    label_map_path = project_dir / "step3_palette" / "label_map.npy"
    palette_path = project_dir / "step3_palette" / "palette.json"

    result = run_step4_raw_regions(
        label_map_path=require_file(label_map_path, "step 3 label map"),
        palette_path=require_file(palette_path, "step 3 palette"),
        output_dir=str(output_dir),
        connectivity=int(params.get("connectivity", 2)),
    )

    return output_dir, result


def run_step_5(
    project_dir: Path,
    original_image: Path,
    params: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """
    Step 5: border smoothing / de-zippering.

    This step can be rerun independently if raw regions are okay,
    but borders need different smoothing params.
    """
    output_dir = project_dir / "step5_border_cleanup"

    label_map_path = project_dir / "step4_raw_regions" / "label_map_raw.npy"
    palette_path = project_dir / "step3_palette" / "palette.json"
    sam_metadata_path = project_dir / "step1_objects" / "metadata.json"

    result = run_step5_border_cleanup(
        label_map_path=require_file(label_map_path, "step 4 raw label map"),
        palette_path=require_file(palette_path, "step 3 palette"),
        output_dir=str(output_dir),

        sam_metadata_path=require_file(
            sam_metadata_path,
            "step 1 SAM metadata",
        ),

        cleanup_boundary_artifacts_enabled=as_bool(
            params.get("cleanup_boundary_artifacts_enabled"),
            default=True,
        ),
        boundary_cleanup_radius=int(params.get("boundary_cleanup_radius", 3)),
        boundary_cleanup_iterations=int(params.get("boundary_cleanup_iterations", 3)),
        boundary_dominance_threshold=float(
            params.get("boundary_dominance_threshold", 0.58)
        ),
        boundary_min_advantage=int(params.get("boundary_min_advantage", 2)),
        boundary_max_current_support_ratio=float(
            params.get("boundary_max_current_support_ratio", 0.45)
        ),

        use_object_guided_cleanup=as_bool(
            params.get("use_object_guided_cleanup"),
            default=True,
        ),
        object_boundary_guard_px=int(params.get("object_boundary_guard_px", 4)),
        cleanup_background=as_bool(
            params.get("cleanup_background"),
            default=True,
        ),

        connectivity=int(params.get("connectivity", 2)),
    )

    return output_dir, result


def run_step_6(
    project_dir: Path,
    original_image: Path,
    params: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """
    Step 6: island cleanup + final region map.

    This creates the final region_map.npy and regions.json that template step uses.
    """
    output_dir = project_dir / "step6_island_cleanup"

    label_map_path = project_dir / "step5_border_cleanup" / "label_map_border_cleaned.npy"
    object_map_path = project_dir / "step5_border_cleanup" / "object_map.npy"
    palette_path = project_dir / "step3_palette" / "palette.json"

    result = run_step6_island_cleanup(
        label_map_path=require_file(
            label_map_path,
            "step 5 border-cleaned label map",
        ),
        palette_path=require_file(palette_path, "step 3 palette"),
        output_dir=str(output_dir),

        object_map_path=require_file(
            object_map_path,
            "step 5 object map",
        ),

        micro_island_cleanup_enabled=as_bool(
            params.get("micro_island_cleanup_enabled"),
            default=True,
        ),
        micro_island_min_area=int(params.get("micro_island_min_area", 80)),
        micro_island_iterations=int(params.get("micro_island_iterations", 4)),
        micro_island_connectivity=int(params.get("micro_island_connectivity", 1)),
        micro_island_same_object_only=as_bool(
            params.get("micro_island_same_object_only"),
            default=True,
        ),

        min_region_area=int(params.get("min_region_area", 700)),

        split_same_color_neighbors=as_bool(
            params.get("split_same_color_neighbors"),
            default=False,
        ),

        connectivity=int(params.get("connectivity", 2)),
    )

    return output_dir, result


def run_step_7(
    project_dir: Path,
    original_image: Path,
    params: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """
    Step 7: template.

    Reads final cleaned regions from Step 6.
    """
    output_dir = project_dir / "step7_template"

    region_map_path = project_dir / "step6_island_cleanup" / "region_map.npy"
    regions_path = project_dir / "step6_island_cleanup" / "regions.json"
    palette_path = project_dir / "step3_palette" / "palette.json"

    result = run_step7_make_template(
        region_map_path=require_file(region_map_path, "step 6 final region map"),
        regions_path=require_file(regions_path, "step 6 final regions"),
        palette_path=require_file(palette_path, "step 3 palette"),
        output_dir=str(output_dir),
        line_thickness=int(params.get("line_thickness", 1)),
        font_size=int(params.get("font_size", 14)),
        min_number_area=int(params.get("min_number_area", 100)),
    )

    return output_dir, result


def run_step_8(
    project_dir: Path,
    original_image: Path,
    params: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """
    Step 8: PDF export.

    The underlying export function may still expect the old Step 5 template filenames.
    If you renamed files inside step7_make_template.py, update these two paths.
    """
    output_dir = project_dir / "step8_pdf"

    template_path = project_dir / "step7_template" / "step7_pbn_template.png"
    palette_sheet_path = project_dir / "step7_template" / "step7_palette_sheet.png"

    result = run_step8_export_pdf(
        template_path=require_file(template_path, "step 7 template"),
        palette_sheet_path=require_file(palette_sheet_path, "step 7 palette sheet"),
        output_dir=str(output_dir),
        page_width_cm=float(params.get("page_width_cm", 29.7)),
        page_height_cm=float(params.get("page_height_cm", 42.0)),
        dpi=int(params.get("dpi", 300)),
        fit_mode=params.get("fit_mode", "cover"),
    )

    return output_dir, result


STEP_DEFINITIONS: dict[int, StepDefinition] = {
    1: StepDefinition(1, "Object masks", "step1_objects", run_step_1),
    2: StepDefinition(2, "Smooth objects", "step2_smooth", run_step_2),
    3: StepDefinition(3, "Global palette", "step3_palette", run_step_3),
    4: StepDefinition(4, "Raw regions", "step4_raw_regions", run_step_4),
    5: StepDefinition(5, "Border smoothing", "step5_border_cleanup", run_step_5),
    6: StepDefinition(6, "Islands cleanup", "step6_island_cleanup", run_step_6),
    7: StepDefinition(7, "Template", "step7_template", run_step_7),
    8: StepDefinition(8, "PDF export", "step8_pdf", run_step_8),
}