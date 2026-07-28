import logging
import json
import urllib.error
import urllib.request

from fastapi import HTTPException

from ai_pipeline.models import ProviderConfigurationError, ProviderRequestError, ProviderResponseError
from ai_pipeline.pipeline import continue_ai_pipeline, finalize_pbn_option, generate_ai_image, run_ai_pipeline
from runner_app.models import (
    ContinueAIPipelineRequest,
    ContinueAIPipelineResponse,
    FinalizePBNOptionRequest,
    FinalizePBNOptionResponse,
    GenerateAIImageRequest,
    GenerateAIImageResponse,
    RunAIPipelineRequest,
    RunAIPipelineResponse,
)
from runner_app.utils import get_project_dir_by_ids, resolve_original_image

logger = logging.getLogger(__name__)


def run_ai_project_pipeline(req: RunAIPipelineRequest) -> RunAIPipelineResponse:
    project_dir = get_project_dir_by_ids(req.project_id, req.public_id)
    original_image = resolve_original_image(project_dir, req.input_path)

    try:
        output_dir, result = run_ai_pipeline(
            project_dir=project_dir,
            original_image=original_image,
            settings=req.settings,
            progress_callback=_progress_callback(req, "ai_processing"),
        )
        return RunAIPipelineResponse(
            ok=True,
            project_id=req.project_id,
            public_id=req.public_id,
            output_dir=str(output_dir),
            result=result,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=424, detail={"error": str(exc)}) from exc
    except (ProviderRequestError, ProviderResponseError) as exc:
        raise HTTPException(status_code=502, detail=_provider_error_detail(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("AI pipeline failed for project_id=%s", req.project_id)
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


def generate_ai_project_image(req: GenerateAIImageRequest) -> GenerateAIImageResponse:
    project_dir = get_project_dir_by_ids(req.project_id, req.public_id)
    original_image = resolve_original_image(project_dir, req.input_path)

    try:
        output_dir, result = generate_ai_image(
            project_dir=project_dir,
            original_image=original_image,
            settings=req.settings,
            progress_callback=_progress_callback(req, "ai_image_processing"),
            force_regenerate=req.force_regenerate,
        )
        return GenerateAIImageResponse(
            ok=True,
            project_id=req.project_id,
            public_id=req.public_id,
            output_dir=str(output_dir),
            result=result,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=424, detail={"error": str(exc)}) from exc
    except (ProviderRequestError, ProviderResponseError) as exc:
        raise HTTPException(status_code=502, detail=_provider_error_detail(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("AI image generation failed for project_id=%s", req.project_id)
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


def continue_ai_project_pipeline(req: ContinueAIPipelineRequest) -> ContinueAIPipelineResponse:
    project_dir = get_project_dir_by_ids(req.project_id, req.public_id)
    original_image = resolve_original_image(project_dir, req.input_path)

    try:
        output_dir, result = continue_ai_pipeline(
            project_dir=project_dir,
            original_image=original_image,
            settings=req.settings,
            progress_callback=_progress_callback(req, "pbn_options_processing"),
        )
        return ContinueAIPipelineResponse(
            ok=True,
            project_id=req.project_id,
            public_id=req.public_id,
            output_dir=str(output_dir),
            result=result,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=424, detail={"error": str(exc)}) from exc
    except (ProviderRequestError, ProviderResponseError) as exc:
        raise HTTPException(status_code=502, detail=_provider_error_detail(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PBN continuation failed for project_id=%s", req.project_id)
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


def finalize_pbn_project_option(req: FinalizePBNOptionRequest) -> FinalizePBNOptionResponse:
    project_dir = get_project_dir_by_ids(req.project_id, req.public_id)
    try:
        output_dir, result = finalize_pbn_option(
            project_dir=project_dir,
            settings=req.settings,
            difficulty=req.difficulty,
            progress_callback=_progress_callback(req, "pbn_selection_processing"),
        )
        return FinalizePBNOptionResponse(
            ok=True,
            project_id=req.project_id,
            public_id=req.public_id,
            output_dir=str(output_dir),
            result=result,
        )
    except Exception as exc:
        logger.exception("PBN option finalization failed for project_id=%s", req.project_id)
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc


def _progress_callback(req: RunAIPipelineRequest, status: str):
    if not req.callback_base or not req.callback_secret:
        return None

    callback_base = req.callback_base.rstrip("/")
    callback_secret = req.callback_secret
    project_id = req.project_id

    def post_progress(stage: str, progress: int, message: str) -> None:
        payload = {
            "status": status,
            "progress": progress,
            "stage": stage,
            "message": message,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{callback_base}/projects/{project_id}/status",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Secret": callback_secret,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning("failed to post AI progress stage=%s project_id=%s: %s", stage, project_id, exc)

    return post_progress


def _provider_error_detail(exc: ProviderRequestError | ProviderResponseError) -> dict[str, object]:
    if isinstance(exc, ProviderRequestError):
        return exc.to_detail()
    return {"error": str(exc)}
