from __future__ import annotations

import logging

from redis import Redis

from .api_client import BackendInternalClient
from .config import WorkerConfig
from .constants import AI_PROGRESS
from .events import EventPublisher
from .file_detection import build_project_root, detect_upload_preview_file, public_ai_files, public_ai_image_files, public_pbn_option_files
from .retry import retry_job
from .runner_client import PythonRunnerClient
from .types import JsonDict

logger = logging.getLogger(__name__)


class JobProcessor:
    def __init__(
        self,
        redis_client: Redis,
        config: WorkerConfig,
        backend: BackendInternalClient,
        runner: PythonRunnerClient,
        events: EventPublisher,
    ) -> None:
        self.redis_client = redis_client
        self.config = config
        self.backend = backend
        self.runner = runner
        self.events = events

    def process(self, payload: JsonDict) -> None:
        job_type = payload.get("type", "run_ai_pipeline")

        if job_type == "generate_upload_preview":
            self.process_upload_preview_job(payload)
            return

        if job_type == "run_ai_pipeline":
            self.process_ai_pipeline_job(payload)
            return

        if job_type == "generate_ai_image":
            self.process_ai_image_job(payload)
            return

        if job_type in {"continue_ai_pipeline", "generate_pbn_options"}:
            self.process_pbn_pipeline_job(payload)
            return

        if job_type == "finalize_pbn_option":
            self.process_pbn_selection_job(payload)
            return

        raise ValueError(f"unknown job type: {job_type}")

    def process_upload_preview_job(self, payload: JsonDict) -> None:
        project_id = payload["project_id"]
        public_id = payload.get("public_id", "")
        input_path = payload.get("input_path")
        project_root = build_project_root(payload, public_id)

        try:
            self.events.publish(
                {
                    "type": "upload_preview_processing",
                    "project_id": public_id,
                    "status": "upload_preview_processing",
                }
            )

            runner_response = self.runner.generate_upload_preview(project_id, public_id, input_path if isinstance(input_path, str) else None)
            local_files = detect_upload_preview_file(project_root)
            saved_files = self.backend.post_files(project_id, local_files) if local_files else []

            self.events.publish(
                {
                    "type": "upload_preview_completed",
                    "project_id": public_id,
                    "status": "uploaded",
                    "files": saved_files,
                    "runner_result": runner_response,
                }
            )

        except Exception as exc:
            logger.exception("upload preview job failed")

            if retry_job(self.redis_client, self.config, self.backend, self.events, payload, exc):
                return

            self.backend.post_status(project_id, "uploaded", 100, "", error_message=str(exc))
            self.events.publish(
                {
                    "type": "upload_preview_failed",
                    "project_id": public_id,
                    "status": "uploaded",
                    "message": str(exc),
                }
            )

    def process_ai_image_job(self, payload: JsonDict) -> None:
        project_id = payload["project_id"]
        public_id = payload.get("public_id", "")
        settings = payload.get("settings") or {}
        input_path = payload.get("input_path")
        project_root = build_project_root(payload, public_id)
        force_regenerate = bool(payload.get("force_regenerate", False))

        try:
            self.backend.post_status(project_id, "ai_image_processing", AI_PROGRESS["generating_ai_image"], "AI image generation started")
            self.events.publish(
                {
                    "type": "ai_status_changed",
                    "project_id": public_id,
                    "status": "ai_image_processing",
                    "stage": "generating_ai_image",
                    "value": AI_PROGRESS["generating_ai_image"],
                }
            )

            runner_response = self.runner.generate_ai_image(
                project_id=project_id,
                public_id=public_id,
                settings=settings,
                input_path=input_path if isinstance(input_path, str) else None,
                force_regenerate=force_regenerate,
            )

            quality = runner_response.get("result", {}).get("metrics", {}).get("ai_quality")
            if not isinstance(quality, dict) or quality.get("status") not in {"pass", "warn"}:
                raise ValueError("runner did not return a valid AI quality assessment")
            self.backend.post_ai_quality(project_id, quality)

            local_files = public_ai_image_files(project_root)
            saved_files = self.backend.post_files(project_id, local_files) if local_files else []

            self.backend.post_status(project_id, "ai_image_ready", 100, "AI image ready for review")
            self.events.publish(
                {
                    "type": "ai_image_ready",
                    "project_id": public_id,
                    "status": "ai_image_ready",
                    "stage": "ai_image_ready",
                    "value": 100,
                    "files": saved_files,
                    "ai_quality": quality,
                    "runner_result": runner_response,
                }
            )

        except Exception as exc:
            logger.exception("AI image generation job failed project_id=%s", project_id)

            if retry_job(self.redis_client, self.config, self.backend, self.events, payload, exc):
                return

            self.backend.post_status(project_id, "ai_failed", 100, str(exc), error_message=str(exc))
            self.events.publish(
                {
                    "type": "ai_failed",
                    "project_id": public_id,
                    "status": "ai_failed",
                    "stage": "failed",
                    "message": str(exc),
                }
            )

    def process_pbn_pipeline_job(self, payload: JsonDict) -> None:
        project_id = payload["project_id"]
        public_id = payload.get("public_id", "")
        settings = payload.get("settings") or {}
        input_path = payload.get("input_path")
        project_root = build_project_root(payload, public_id)

        try:
            self.backend.post_status(project_id, "pbn_options_processing", AI_PROGRESS["extracting_regions"], "PBN option generation started")
            self.events.publish(
                {
                    "type": "ai_status_changed",
                    "project_id": public_id,
                    "status": "pbn_options_processing",
                    "stage": "extracting_regions",
                    "value": AI_PROGRESS["extracting_regions"],
                }
            )

            runner_response = self.runner.continue_ai_pipeline(
                project_id=project_id,
                public_id=public_id,
                settings=settings,
                input_path=input_path if isinstance(input_path, str) else None,
            )

            options = runner_response.get("result", {}).get("metrics", {}).get("options", [])
            if not isinstance(options, list) or not options:
                raise ValueError("runner did not return any valid PBN options")
            self.backend.post_pbn_options(project_id, options)
            local_files = public_pbn_option_files(project_root)
            saved_files = self.backend.post_files(project_id, local_files) if local_files else []

            self.backend.post_status(project_id, "pbn_options_ready", 100, "PBN difficulty options are ready")
            self.events.publish(
                {
                    "type": "pbn_options_ready",
                    "project_id": public_id,
                    "status": "pbn_options_ready",
                    "stage": "options_ready",
                    "value": 100,
                    "files": saved_files,
                    "runner_result": runner_response,
                }
            )

        except Exception as exc:
            logger.exception("PBN continuation job failed project_id=%s", project_id)

            if retry_job(self.redis_client, self.config, self.backend, self.events, payload, exc):
                return

            self.backend.post_status(project_id, "pbn_failed", 100, str(exc), error_message=str(exc))
            self.events.publish(
                {
                    "type": "pbn_failed",
                    "project_id": public_id,
                    "status": "pbn_failed",
                    "stage": "failed",
                    "message": str(exc),
                }
            )

    def process_pbn_selection_job(self, payload: JsonDict) -> None:
        project_id = payload["project_id"]
        public_id = payload.get("public_id", "")
        settings = payload.get("settings") or {}
        difficulty = str(payload.get("difficulty", ""))
        input_path = payload.get("input_path")
        project_root = build_project_root(payload, public_id)
        try:
            self.backend.post_status(project_id, "pbn_selection_processing", AI_PROGRESS["generating_template"], f"Finalizing {difficulty} PBN")
            self.events.publish({"type": "ai_status_changed", "project_id": public_id, "status": "pbn_selection_processing", "stage": "generating_template", "value": AI_PROGRESS["generating_template"]})
            runner_response = self.runner.finalize_pbn_option(
                project_id=project_id,
                public_id=public_id,
                settings=settings,
                difficulty=difficulty,
                input_path=input_path if isinstance(input_path, str) else None,
            )
            local_files = public_ai_files(project_root)
            saved_files = self.backend.post_files(project_id, local_files) if local_files else []
            self.backend.post_pbn_selection(project_id, difficulty)
            self.backend.post_status(project_id, "ai_completed", 100, f"{difficulty.title()} PBN completed")
            self.events.publish({"type": "ai_completed", "project_id": public_id, "status": "ai_completed", "stage": "completed", "value": 100, "files": saved_files, "runner_result": runner_response, "selected_difficulty": difficulty})
        except Exception as exc:
            logger.exception("PBN option finalization failed project_id=%s", project_id)
            if retry_job(self.redis_client, self.config, self.backend, self.events, payload, exc):
                return
            self.backend.post_status(project_id, "pbn_selection_failed", 100, str(exc), error_message=str(exc))
            self.events.publish({"type": "pbn_selection_failed", "project_id": public_id, "status": "pbn_selection_failed", "stage": "failed", "message": str(exc)})

    def process_ai_pipeline_job(self, payload: JsonDict) -> None:
        project_id = payload["project_id"]
        public_id = payload.get("public_id", "")
        settings = payload.get("settings") or {}
        input_path = payload.get("input_path")
        project_root = build_project_root(payload, public_id)

        try:
            self.backend.post_status(project_id, "ai_processing", AI_PROGRESS["generating_ai_image"], "AI generation started")
            self.events.publish(
                {
                    "type": "ai_status_changed",
                    "project_id": public_id,
                    "status": "ai_processing",
                    "stage": "generating_ai_image",
                    "value": AI_PROGRESS["generating_ai_image"],
                }
            )

            runner_response = self.runner.run_ai_pipeline(
                project_id=project_id,
                public_id=public_id,
                settings=settings,
                input_path=input_path if isinstance(input_path, str) else None,
            )

            options = runner_response.get("result", {}).get("metrics", {}).get("options", [])
            if not isinstance(options, list) or not options:
                raise ValueError("runner did not return any valid PBN options")
            self.backend.post_pbn_options(project_id, options)
            local_files = public_pbn_option_files(project_root)
            saved_files = self.backend.post_files(project_id, local_files) if local_files else []

            self.backend.post_status(project_id, "pbn_options_ready", 100, "PBN difficulty options are ready")
            self.events.publish(
                {
                    "type": "pbn_options_ready",
                    "project_id": public_id,
                    "status": "pbn_options_ready",
                    "stage": "options_ready",
                    "value": 100,
                    "files": saved_files,
                    "runner_result": runner_response,
                }
            )

        except Exception as exc:
            logger.exception("AI pipeline job failed project_id=%s", project_id)

            if retry_job(self.redis_client, self.config, self.backend, self.events, payload, exc):
                return

            self.backend.post_status(project_id, "ai_failed", 100, str(exc), error_message=str(exc))
            self.events.publish(
                {
                    "type": "ai_failed",
                    "project_id": public_id,
                    "status": "ai_failed",
                    "stage": "failed",
                    "message": str(exc),
                }
            )
