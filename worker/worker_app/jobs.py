from __future__ import annotations

import logging

from redis import Redis

from .api_client import BackendInternalClient
from .config import WorkerConfig
from .constants import STEP_PROGRESS
from .events import EventPublisher
from .file_detection import build_project_root, detect_upload_preview_file, public_step_files
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
        job_type = payload.get("type", "run_step")

        if job_type == "generate_upload_preview":
            self.process_upload_preview_job(payload)
            return

        if job_type == "run_step":
            self.process_step_job(payload)
            return

        raise ValueError(f"unknown job type: {job_type}")

    def process_upload_preview_job(self, payload: JsonDict) -> None:
        project_id = payload["project_id"]
        public_id = payload.get("public_id", "")
        project_root = build_project_root(payload, public_id)

        try:
            self.events.publish(
                {
                    "type": "upload_preview_processing",
                    "project_id": public_id,
                    "status": "upload_preview_processing",
                }
            )

            runner_response = self.runner.generate_upload_preview(project_id, public_id)

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

            self.events.publish(
                {
                    "type": "upload_preview_failed",
                    "project_id": public_id,
                    "status": "uploaded",
                    "message": str(exc),
                }
            )

    def process_step_job(self, payload: JsonDict) -> None:
        project_id = payload["project_id"]
        public_id = payload.get("public_id", "")
        step = int(payload.get("step", 0))
        parameters = payload.get("parameters") or {}

        if step < 1 or step > 8:
            raise ValueError(f"invalid step: {step}")

        project_root = build_project_root(payload, public_id)
        processing_status = f"step_{step}_processing"
        completed_status = f"step_{step}_completed"
        final_completed_status = "completed" if step == 8 else completed_status
        progress = STEP_PROGRESS.get(step, 0)

        try:
            self.backend.post_status(
                project_id,
                processing_status,
                max(progress - 10, 1),
                f"step {step} started",
            )

            self.events.publish(
                {
                    "type": "status_changed",
                    "project_id": public_id,
                    "status": processing_status,
                    "step": step,
                }
            )

            runner_response = self.runner.run_step(
                step=step,
                project_id=project_id,
                public_id=public_id,
                parameters=parameters,
            )

            local_files = public_step_files(project_root, step)
            saved_files = self.backend.post_files(project_id, local_files) if local_files else []

            self.backend.post_status(
                project_id,
                final_completed_status,
                progress,
                f"step {step} completed",
            )

            self.events.publish(
                {
                    "type": "step_completed",
                    "project_id": public_id,
                    "status": final_completed_status,
                    "step": step,
                    "value": progress,
                    "files": saved_files,
                    "runner_result": runner_response,
                }
            )

        except Exception as exc:
            logger.exception("step job failed step=%s project_id=%s", step, project_id)

            if retry_job(self.redis_client, self.config, self.backend, self.events, payload, exc):
                return

            failed_status = f"step_{step}_failed"
            self.backend.post_status(project_id, "failed", 100, str(exc))

            self.events.publish(
                {
                    "type": "failed",
                    "project_id": public_id,
                    "status": failed_status,
                    "step": step,
                    "message": str(exc),
                }
            )
