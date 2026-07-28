from __future__ import annotations

import json
from redis import Redis

from .api_client import BackendInternalClient
from .config import WorkerConfig
from .events import EventPublisher
from .types import JsonDict


def retry_job(
    redis_client: Redis,
    config: WorkerConfig,
    backend: BackendInternalClient,
    events: EventPublisher,
    payload: JsonDict,
    exc: Exception,
) -> bool:
    if getattr(exc, "retryable", True) is False:
        return False

    retry_count = int(payload.get("retry_count", 0))
    max_retries = int(payload.get("max_retries", 2))

    if retry_count >= max_retries:
        return False

    project_id = payload["project_id"]
    public_id = payload.get("public_id", "")
    job_type = payload.get("type", "run_ai_pipeline")

    payload["retry_count"] = retry_count + 1
    redis_client.rpush(config.queue_name, json.dumps(payload))

    if job_type == "generate_upload_preview":
        status = "upload_preview_queued"
        event_type = "status_changed"
    elif job_type == "generate_ai_image":
        status = "ai_image_queued"
        event_type = "ai_status_changed"
    elif job_type in {"continue_ai_pipeline", "generate_pbn_options"}:
        status = "pbn_options_queued"
        event_type = "ai_status_changed"
    elif job_type == "finalize_pbn_option":
        status = "pbn_selection_queued"
        event_type = "ai_status_changed"
    else:
        status = "ai_queued"
        event_type = "ai_status_changed"

    applied = backend.post_status(
        project_id,
        status,
        0,
        f"retry {payload['retry_count']}/{max_retries}: {exc}",
    )

    if applied is False:
        return True

    events.publish(
        {
            "type": event_type,
            "project_id": public_id,
            "status": status,
            "stage": "queued",
            "message": str(exc),
        }
    )

    return True
