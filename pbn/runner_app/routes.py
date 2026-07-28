from typing import Any

from fastapi import APIRouter

from runner_app.config import PROJECTS_DIR
from runner_app.models import (
    ContinueAIPipelineRequest,
    ContinueAIPipelineResponse,
    FinalizePBNOptionRequest,
    FinalizePBNOptionResponse,
    GenerateAIImageRequest,
    GenerateAIImageResponse,
    RunAIPipelineRequest,
    RunAIPipelineResponse,
    UploadPreviewRequest,
    UploadPreviewResponse,
)
from runner_app.ai_service import continue_ai_project_pipeline, finalize_pbn_project_option, generate_ai_project_image, run_ai_project_pipeline
from runner_app.preview import create_upload_preview, upload_preview_result
from runner_app.utils import get_project_dir_by_ids, resolve_original_image

router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "projects_dir": str(PROJECTS_DIR),
    }


@router.post("/generate-upload-preview", response_model=UploadPreviewResponse)
def generate_upload_preview(req: UploadPreviewRequest) -> UploadPreviewResponse:
    project_dir = get_project_dir_by_ids(req.project_id, req.public_id)
    original_image = resolve_original_image(project_dir, req.input_path)

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


@router.post("/run-ai-pipeline", response_model=RunAIPipelineResponse)
def run_ai_pipeline(req: RunAIPipelineRequest) -> RunAIPipelineResponse:
    return run_ai_project_pipeline(req)


@router.post("/generate-ai-image", response_model=GenerateAIImageResponse)
def generate_ai_image(req: GenerateAIImageRequest) -> GenerateAIImageResponse:
    return generate_ai_project_image(req)


@router.post("/continue-ai-pipeline", response_model=ContinueAIPipelineResponse)
def continue_ai_pipeline(req: ContinueAIPipelineRequest) -> ContinueAIPipelineResponse:
    return continue_ai_project_pipeline(req)


@router.post("/finalize-pbn-option", response_model=FinalizePBNOptionResponse)
def finalize_pbn_option(req: FinalizePBNOptionRequest) -> FinalizePBNOptionResponse:
    return finalize_pbn_project_option(req)
