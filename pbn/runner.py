import os
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from step1_sam_objects import run_step1_sam_objects
from step2_smooth_segments import run_step2_smooth_segments
from step3_global_palette import run_step3_global_palette
from step4_regions_cleanup import run_step4_regions_cleanup
from step5_make_template import run_step5_make_template
from step6_export_pdf import run_step6_export_pdf


PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", "/storage/projects"))

SAM2_CHECKPOINT = os.getenv(
    "SAM2_CHECKPOINT",
    "/app/checkpoints/sam2.1_hiera_base_plus.pt",
)

SAM2_MODEL_CFG = os.getenv(
    "SAM2_MODEL_CFG",
    "configs/sam2.1/sam2.1_hiera_b+.yaml",
)


app = FastAPI(title="PBN Python Runner")


class RunStepRequest(BaseModel):
    project_id: str
    public_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RunStepResponse(BaseModel):
    ok: bool
    step: int
    project_id: str
    public_id: str | None = None
    output_dir: str
    result: dict[str, Any]


def get_project_dir(req: RunStepRequest) -> Path:
    folder_name = req.public_id or req.project_id
    project_dir = PROJECTS_DIR / folder_name

    if not project_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Project directory not found: {project_dir}",
        )

    return project_dir


def find_original_image(project_dir: Path) -> Path:
    candidates = [
        project_dir / "original.png",
        project_dir / "original.jpg",
        project_dir / "original.jpeg",
        project_dir / "original.webp",
    ]

    original_dir = project_dir / "original"

    if original_dir.exists():
        for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
            candidates.extend(sorted(original_dir.glob(ext)))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise HTTPException(
        status_code=400,
        detail=f"Original image not found in {project_dir}",
    )


def require_file(path: Path, label: str) -> str:
    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Missing {label}: {path}",
        )

    return str(path)


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.lower().strip() in {"1", "true", "yes", "y", "on"}

    return bool(value)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "projects_dir": str(PROJECTS_DIR),
        "sam2_checkpoint": SAM2_CHECKPOINT,
        "sam2_model_cfg": SAM2_MODEL_CFG,
    }


@app.post("/run-step/{step}", response_model=RunStepResponse)
def run_step(step: int, req: RunStepRequest) -> RunStepResponse:
    if step < 1 or step > 6:
        raise HTTPException(
            status_code=400,
            detail="Step must be between 1 and 6",
        )

    project_dir = get_project_dir(req)
    original_image = find_original_image(project_dir)
    params = req.params or {}

    try:
        if step == 1:
            output_dir = project_dir / "step1_objects"

            result = run_step1_sam_objects(
                image_path=str(original_image),
                output_dir=str(output_dir),
                checkpoint=params.get("checkpoint", SAM2_CHECKPOINT),
                model_cfg=params.get("model_cfg", SAM2_MODEL_CFG),
                points_per_side=int(params.get("points_per_side", 32)),
                pred_iou_thresh=float(params.get("pred_iou_thresh", 0.88)),
                stability_score_thresh=float(
                    params.get("stability_score_thresh", 0.92)
                ),
                min_mask_region_area=int(
                    params.get("min_mask_region_area", 400)
                ),
                min_area_ratio=float(params.get("min_area_ratio", 0.002)),
                max_area_ratio=float(params.get("max_area_ratio", 0.80)),
                dedupe_iou=float(params.get("dedupe_iou", 0.92)),
            )

        elif step == 2:
            output_dir = project_dir / "step2_smooth"

            metadata_path = project_dir / "step1_objects" / "metadata.json"

            result = run_step2_smooth_segments(
                image_path=str(original_image),
                metadata_path=require_file(metadata_path, "step 1 metadata"),
                output_dir=str(output_dir),
                colors_per_object=int(params.get("colors_per_object", 5)),
                background_colors=int(params.get("background_colors", 6)),
                min_region_area=int(params.get("min_region_area", 300)),
                process_background=as_bool(
                    params.get("process_background"),
                    default=True,
                ),
                max_objects=int(params.get("max_objects", 80)),
            )

        elif step == 3:
            output_dir = project_dir / "step3_palette"

            step2_image = project_dir / "step2_smooth" / "step2_smoothed.png"

            result = run_step3_global_palette(
                image_path=require_file(step2_image, "step 2 smoothed image"),
                output_dir=str(output_dir),
                palette_size=int(params.get("palette_size", 30)),
            )

        elif step == 4:
            output_dir = project_dir / "step4_regions"

            label_map_path = project_dir / "step3_palette" / "label_map.npy"
            palette_path = project_dir / "step3_palette" / "palette.json"

            result = run_step4_regions_cleanup(
                label_map_path=require_file(label_map_path, "step 3 label map"),
                palette_path=require_file(palette_path, "step 3 palette"),
                output_dir=str(output_dir),
                min_region_area=int(params.get("min_region_area", 250)),
                split_same_color_neighbors=as_bool(
                    params.get("split_same_color_neighbors"),
                    default=False,
                ),
            )

        elif step == 5:
            output_dir = project_dir / "step5_template"

            region_map_path = project_dir / "step4_regions" / "region_map.npy"
            regions_path = project_dir / "step4_regions" / "regions.json"
            palette_path = project_dir / "step3_palette" / "palette.json"

            result = run_step5_make_template(
                region_map_path=require_file(region_map_path, "step 4 region map"),
                regions_path=require_file(regions_path, "step 4 regions"),
                palette_path=require_file(palette_path, "step 3 palette"),
                output_dir=str(output_dir),
                line_thickness=int(params.get("line_thickness", 1)),
                font_size=int(params.get("font_size", 14)),
                min_number_area=int(params.get("min_number_area", 100)),
            )

        else:
            output_dir = project_dir / "step6_pdf"

            template_path = project_dir / "step5_template" / "pbn_template.png"
            palette_sheet_path = project_dir / "step5_template" / "palette_sheet.png"

            result = run_step6_export_pdf(
                template_path=require_file(template_path, "step 5 template"),
                palette_sheet_path=require_file(
                    palette_sheet_path,
                    "step 5 palette sheet",
                ),
                output_dir=str(output_dir),
                page_width_cm=float(params.get("page_width_cm", 29.7)),
                page_height_cm=float(params.get("page_height_cm", 42.0)),
                dpi=int(params.get("dpi", 300)),
            )

        return RunStepResponse(
            ok=True,
            step=step,
            project_id=req.project_id,
            public_id=req.public_id,
            output_dir=str(output_dir),
            result=result,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )