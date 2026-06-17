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
    retry_count = int(payload.get("retry_count", 0))
    max_retries = int(payload.get("max_retries", 2))

    if retry_count >= max_retries:
        return False

    payload["retry_count"] = retry_count + 1
    redis_client.rpush(config.queue_name, json.dumps(payload))

    project_id = payload["project_id"]
    public_id = payload.get("public_id", "")
    step = int(payload.get("step", 0))
    job_type = payload.get("type", "run_step")

    status = "upload_preview_queued" if job_type == "generate_upload_preview" else f"step_{step}_queued"

    backend.post_status(
        project_id,
        status,
        0,
        f"retry {payload['retry_count']}/{max_retries}: {exc}",
    )

    events.publish(
        {
            "type": "status_changed",
            "project_id": public_id,
            "status": status,
            "step": step,
            "message": str(exc),
        }
    )

    return True
