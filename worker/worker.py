import json
import logging
import mimetypes
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

REDIS_ADDR = os.getenv("REDIS_ADDR", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

QUEUE_NAME = os.getenv("REDIS_QUEUE_NAME", "pbn:jobs")
EVENTS_CHANNEL = os.getenv("REDIS_EVENTS_CHANNEL", "pbn:events")
CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "3"))

API_BASE = os.getenv("BACKEND_INTERNAL_BASE", "http://backend:8080/api/internal")
API_SECRET = os.getenv("INTERNAL_API_SECRET", "local-dev-secret")

PYTHON_RUNNER_BASE_URL = os.getenv(
    "PYTHON_RUNNER_BASE_URL",
    "http://pbn:8081",
)

STEP_PROGRESS = {
    1: 15,
    2: 30,
    3: 45,
    4: 65,
    5: 85,
    6: 100,
}


def post_status(
    project_id: str,
    status: str,
    progress: int = 0,
    message: str = "",
) -> None:
    try:
        requests.post(
            f"{API_BASE}/projects/{project_id}/status",
            headers={"X-Internal-Secret": API_SECRET},
            timeout=15,
            json={
                "status": status,
                "progress": progress,
                "message": message,
            },
        ).raise_for_status()
    except Exception:
        print(f"failed to post status: {status} ({progress}%) - {message}")

def post_files(project_id: str, files: list[dict[str, Any]]) -> None:
    try:
        requests.post(
            f"{API_BASE}/projects/{project_id}/files",
            headers={"X-Internal-Secret": API_SECRET},
            timeout=30,
            json={"files": files},
        ).raise_for_status()
    except Exception:
        print(f"failed to post files for project {project_id}")


def publish_event(redis_client: Redis, payload: dict[str, Any]) -> None:
    try:
        redis_client.publish(EVENTS_CHANNEL, json.dumps(payload))
    except Exception:
        print("failed to publish redis event")


def detect_files(output_path: Path) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []

    if not output_path.exists():
        return discovered

    for path in sorted(output_path.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(output_path)
        file_type = str(rel.with_suffix("")).replace("\\", "_").replace("/", "_")

        mime_type, _ = mimetypes.guess_type(path.name)
        if not mime_type:
            mime_type = "application/octet-stream"

        discovered.append(
            {
                "file_type": file_type,
                "filename": path.name,
                "file_path": str(path),
                "mime_type": mime_type,
                "size_bytes": path.stat().st_size,
            }
        )

    return discovered


def detect_step_files(project_root: Path, step: int) -> list[dict[str, Any]]:
    step_dirs = {
        1: "step1_objects",
        2: "step2_smooth",
        3: "step3_palette",
        4: "step4_regions",
        5: "step5_template",
        6: "step6_pdf",
    }

    step_dir_name = step_dirs.get(step)

    if not step_dir_name:
        return []

    step_dir = project_root / step_dir_name

    files = detect_files(step_dir)

    for file in files:
        file["file_type"] = f"step{step}_{file['file_type']}"

    return files


def call_python_runner(
    step: int,
    project_id: str,
    public_id: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    response = requests.post(
        f"{PYTHON_RUNNER_BASE_URL}/run-step/{step}",
        timeout=60 * 60,
        json={
            "project_id": project_id,
            "public_id": public_id,
            "params": parameters,
        },
    )

    response.raise_for_status()

    return response.json()


def retry_job(
    redis_client: Redis,
    payload: dict[str, Any],
    exc: Exception,
) -> bool:
    retry_count = int(payload.get("retry_count", 0))
    max_retries = int(payload.get("max_retries", 2))

    if retry_count >= max_retries:
        return False

    payload["retry_count"] = retry_count + 1

    redis_client.rpush(QUEUE_NAME, json.dumps(payload))

    project_id = payload["project_id"]
    public_id = payload.get("public_id", "")
    step = int(payload.get("step", 0))

    status = f"step_{step}_queued" if step else "queued"

    post_status(
        project_id,
        status,
        0,
        f"retry {payload['retry_count']}/{max_retries}: {exc}",
    )

    publish_event(
        redis_client,
        {
            "type": "status_changed",
            "project_id": public_id,
            "status": status,
            "step": step,
            "message": str(exc),
        },
    )

    return True


def process_job(redis_client: Redis, payload: dict[str, Any]) -> None:
    project_id = payload["project_id"]
    public_id = payload.get("public_id", "")
    step = int(payload.get("step", 0))
    parameters = payload.get("parameters") or {}

    if step < 1 or step > 6:
        raise ValueError(f"invalid step: {step}")

    project_root = Path(
        payload.get("project_root")
        or payload.get("output_path")
        or f"/storage/projects/{public_id}"
    )

    processing_status = f"step_{step}_processing"
    completed_status = f"step_{step}_completed"

    if step == 6:
        final_completed_status = "completed"
    else:
        final_completed_status = completed_status

    progress = STEP_PROGRESS.get(step, 0)

    post_status(
        project_id,
        processing_status,
        max(progress - 10, 1),
        f"step {step} started",
    )

    publish_event(
        redis_client,
        {
            "type": "status_changed",
            "project_id": public_id,
            "status": processing_status,
            "step": step,
        },
    )

    try:
        runner_response = call_python_runner(
            step=step,
            project_id=project_id,
            public_id=public_id,
            parameters=parameters,
        )

        files = detect_step_files(project_root, step)

        post_files(project_id, files)

        post_status(
            project_id,
            final_completed_status,
            progress,
            f"step {step} completed",
        )

        publish_event(
            redis_client,
            {
                "type": "step_completed",
                "project_id": public_id,
                "status": final_completed_status,
                "step": step,
                "value": progress,
                "files": files,
                "runner_result": runner_response.get("result"),
            },
        )

        if step == 6:
            publish_event(
                redis_client,
                {
                    "type": "completed",
                    "project_id": public_id,
                    "status": "completed",
                    "files": files,
                },
            )

    except Exception as exc:
        print(f"step job failed: {exc}")

        if retry_job(redis_client, payload, exc):
            return

        failed_status = f"step_{step}_failed"

        post_status(
            project_id,
            "failed",
            100,
            str(exc),
        )

        publish_event(
            redis_client,
            {
                "type": "failed",
                "project_id": public_id,
                "status": failed_status,
                "step": step,
                "message": str(exc),
            },
        )


def worker_loop(worker_name: str) -> None:
    redis_client = Redis(
        host=REDIS_ADDR,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )

    print(f"worker started: {worker_name}")

    while True:
        try:
            item = redis_client.blpop(QUEUE_NAME, timeout=5)

            if not item:
                continue

            _, raw_payload = item

            payload = json.loads(raw_payload)

            process_job(redis_client, payload)

        except RedisTimeoutError:
            continue

        except RedisConnectionError:
            print("redis connection issue in worker loop; retrying")
            time.sleep(2)
            continue

        except Exception:
            print("worker loop error")
            time.sleep(2)


def main() -> None:
    threads: list[threading.Thread] = []

    for i in range(CONCURRENCY):
        thread = threading.Thread(
            target=worker_loop,
            args=(f"worker-{i + 1}",),
            daemon=True,
        )

        thread.start()

        threads.append(thread)

    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()