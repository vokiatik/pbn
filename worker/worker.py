import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests
from redis import Redis

from main import run as pipeline_run
from pbn.config import PipelineConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pbn-worker")

REDIS_ADDR = os.getenv("REDIS_ADDR", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
QUEUE_NAME = os.getenv("REDIS_QUEUE_NAME", "pbn:jobs")
EVENTS_CHANNEL = os.getenv("REDIS_EVENTS_CHANNEL", "pbn:events")
CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "3"))
API_BASE = os.getenv("BACKEND_INTERNAL_BASE", "http://backend:8080/api/internal")
API_SECRET = os.getenv("INTERNAL_API_SECRET", "local-dev-secret")

STAGE_PROGRESS = {
    "[1/8]": 10,
    "[2/8]": 20,
    "[3/8]": 35,
    "[4/8]": 50,
    "[5/8]": 65,
    "[6/8]": 80,
    "[7/8]": 90,
    "[8/8]": 95,
}


def post_status(project_id: str, status: str, progress: int = 0, message: str = "") -> None:
    try:
        requests.post(
            f"{API_BASE}/projects/{project_id}/status",
            headers={"X-Internal-Secret": API_SECRET},
            timeout=10,
            json={"status": status, "progress": progress, "message": message},
        ).raise_for_status()
    except Exception:
        logger.exception("failed to post status")


def post_files(project_id: str, files: list[dict[str, Any]]) -> None:
    try:
        requests.post(
            f"{API_BASE}/projects/{project_id}/files",
            headers={"X-Internal-Secret": API_SECRET},
            timeout=20,
            json={"files": files},
        ).raise_for_status()
    except Exception:
        logger.exception("failed to post files")


def publish_event(redis_client: Redis, payload: dict[str, Any]) -> None:
    try:
        redis_client.publish(EVENTS_CHANNEL, json.dumps(payload))
    except Exception:
        logger.exception("failed to publish redis event")


def detect_files(output_path: Path) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    if not output_path.exists():
        return discovered

    for p in sorted(output_path.glob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".json", ".pdf"}:
            continue
        file_type = p.stem
        mime_type = "application/octet-stream"
        if ext == ".png":
            mime_type = "image/png"
        elif ext in {".jpg", ".jpeg"}:
            mime_type = "image/jpeg"
        elif ext == ".json":
            mime_type = "application/json"
        elif ext == ".pdf":
            mime_type = "application/pdf"

        discovered.append(
            {
                "file_type": file_type,
                "filename": p.name,
                "file_path": str(p),
                "mime_type": mime_type,
                "size_bytes": p.stat().st_size,
            }
        )
    return discovered


def build_config(payload: dict[str, Any]) -> PipelineConfig:
    params = payload.get("parameters") or {}
    return PipelineConfig(
        input_path=Path(payload["input_path"]),
        out_dir=Path(payload["output_path"]),
        colors=int(params.get("colors", 32)),
        size=int(params.get("size", 2200)),
        min_region_area=params.get("min_region_area", 24),
        superpixel_area_px=int(params.get("superpixel_area_px", 320)),
        superpixel_shape=str(params.get("superpixel_shape", "adaptive")),
        superpixels_min=int(params.get("superpixels_min", 12000)),
        superpixels_max=int(params.get("superpixels_max", 40000)),
        detail_level=float(params.get("detail_level", 1.0)),
        edge_threshold=float(params.get("edge_threshold", 0.14)),
        lab_merge_threshold=float(params.get("lab_merge_threshold", 16.0)),
        merge_iterations=int(params.get("merge_iterations", 12)),
        line_width=int(params.get("line_width", 1)),
        min_number_area=params.get("min_number_area", None),
        cleanup_passes=int(params.get("cleanup_passes", 0)),
        export_pdf=bool(params.get("export_pdf", False)),
        seed=int(params.get("seed", 42)),
        importance_mask_path=Path(params["importance_mask_path"]) if params.get("importance_mask_path") else None,
        preserve_detail_regions=bool(params.get("preserve_detail_regions", True)),
        print_format=str(params.get("print_format", "a4")),
    )


def process_job(redis_client: Redis, payload: dict[str, Any]) -> None:
    project_id = payload["project_id"]
    public_id = payload.get("public_id", "")
    retry_count = int(payload.get("retry_count", 0))
    max_retries = int(payload.get("max_retries", 2))

    post_status(project_id, "processing", 1, "processing started")
    publish_event(
        redis_client,
        {"type": "status_changed", "project_id": public_id, "status": "processing"},
    )

    config = build_config(payload)

    import builtins

    original_print = builtins.print

    def wrapped_print(*args: Any, **kwargs: Any) -> None:
        text = " ".join(str(a) for a in args)
        for marker, progress in STAGE_PROGRESS.items():
            if marker in text:
                post_status(project_id, "processing", progress, text)
                publish_event(
                    redis_client,
                    {
                        "type": "progress",
                        "project_id": public_id,
                        "status": "processing",
                        "value": progress,
                        "message": text,
                    },
                )
                break
        original_print(*args, **kwargs)

    try:
        builtins.print = wrapped_print
        pipeline_run(config)
        files = detect_files(Path(payload["output_path"]))
        post_files(project_id, files)
        post_status(project_id, "completed", 100, "processing completed")
        publish_event(
            redis_client,
            {"type": "completed", "project_id": public_id, "files": files},
        )
    except Exception as exc:
        logger.exception("job failed")
        if retry_count < max_retries:
            payload["retry_count"] = retry_count + 1
            redis_client.rpush(QUEUE_NAME, json.dumps(payload))
            post_status(project_id, "queued", 0, f"retry {payload['retry_count']}/{max_retries}")
            publish_event(
                redis_client,
                {
                    "type": "status_changed",
                    "project_id": public_id,
                    "status": "queued",
                    "message": str(exc),
                },
            )
            return
        post_status(project_id, "failed", 100, str(exc))
        publish_event(
            redis_client,
            {
                "type": "failed",
                "project_id": public_id,
                "status": "failed",
                "message": str(exc),
            },
        )
    finally:
        builtins.print = original_print


def worker_loop(worker_name: str) -> None:
    redis_client = Redis(host=REDIS_ADDR, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)
    logger.info("worker started", extra={"worker": worker_name})

    while True:
        try:
            item = redis_client.blpop(QUEUE_NAME, timeout=5)
            if not item:
                continue
            _, raw_payload = item
            payload = json.loads(raw_payload)
            process_job(redis_client, payload)
        except Exception:
            logger.exception("worker loop error")
            time.sleep(2)


def main() -> None:
    threads = []
    for i in range(CONCURRENCY):
        t = threading.Thread(target=worker_loop, args=(f"worker-{i+1}",), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
