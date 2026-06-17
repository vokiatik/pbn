from typing import Any

from fastapi import APIRouter

from runner_app.config import PROJECTS_DIR, SAM2_CHECKPOINT, SAM2_MODEL_CFG
from runner_app.models import (
    RunStepRequest,
    RunStepResponse,
    UploadPreviewRequest,
    UploadPreviewResponse,
)
from runner_app.preview import create_upload_preview, upload_preview_result
from runner_app.step_service import run_project_step
from runner_app.utils import find_original_image, get_project_dir_by_ids

router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "projects_dir": str(PROJECTS_DIR),
        "sam2_checkpoint": SAM2_CHECKPOINT,
        "sam2_model_cfg": SAM2_MODEL_CFG,
    }


@router.post("/generate-upload-preview", response_model=UploadPreviewResponse)
def generate_upload_preview(req: UploadPreviewRequest) -> UploadPreviewResponse:
    project_dir = get_project_dir_by_ids(req.project_id, req.public_id)
    original_image = find_original_image(project_dir)

    preview_path = create_upload_preview(
        original_image=original_image,
        project_dir=project_dir,
    )

    return UploadPreviewResponse(
        ok=True,
        project_id=req.project_id,
        public_id=req.public_id,
        output_dir=str(preview_path.parent),
        preview_path=str(preview_path),
        result=upload_preview_result(preview_path),
    )


@router.post("/run-step/{step}", response_model=RunStepResponse)
def run_step(step: int, req: RunStepRequest) -> RunStepResponse:
    return run_project_step(step, req)
