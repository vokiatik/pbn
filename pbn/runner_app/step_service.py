import logging
import traceback
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from runner_app.models import RunStepRequest, RunStepResponse
from runner_app.step_definitions import STEP_DEFINITIONS
from runner_app.utils import find_original_image, get_project_dir_by_ids

logger = logging.getLogger(__name__)


def run_project_step(step: int, req: RunStepRequest) -> RunStepResponse:
    if step not in STEP_DEFINITIONS:
        raise HTTPException(
            status_code=400,
            detail="Step must be between 1 and 8",
        )

    project_dir = get_project_dir_by_ids(req.project_id, req.public_id)
    original_image = find_original_image(project_dir)
    params: dict[str, Any] = req.params or {}

    definition = STEP_DEFINITIONS[step]

    logger.info(
        "running step %s (%s) for project_id=%s public_id=%s params=%s",
        step,
        definition.title,
        req.project_id,
        req.public_id,
        params,
    )

    try:
        output_dir, result = definition.runner(project_dir, original_image, params)

        logger.info(
            "completed step %s (%s) for project_id=%s public_id=%s output_dir=%s",
            step,
            definition.title,
            req.project_id,
            req.public_id,
            output_dir,
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
        logger.exception(
            "step %s failed with HTTPException for project_id=%s public_id=%s",
            step,
            req.project_id,
            req.public_id,
        )
        raise

    except Exception as exc:
        logger.exception(
            "step %s failed for project_id=%s public_id=%s",
            step,
            req.project_id,
            req.public_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        ) from exc
