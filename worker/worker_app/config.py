from __future__ import annotations

import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerConfig:
    redis_addr: str
    redis_port: int
    redis_db: int
    redis_password: str | None
    queue_name: str
    events_channel: str
    concurrency: int
    api_base: str
    api_secret: str
    python_runner_base_url: str


def load_config() -> WorkerConfig:
    return WorkerConfig(
        redis_addr=os.getenv("REDIS_ADDR", "redis"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        redis_db=int(os.getenv("REDIS_DB", "0")),
        redis_password=os.getenv("REDIS_PASSWORD"),
        queue_name=os.getenv("REDIS_QUEUE_NAME", "pbn:jobs"),
        events_channel=os.getenv("REDIS_EVENTS_CHANNEL", "pbn:events"),
        concurrency=int(os.getenv("WORKER_CONCURRENCY", "3")),
        api_base=os.getenv("BACKEND_INTERNAL_BASE", "http://backend:8080/api/internal"),
        api_secret=os.getenv("INTERNAL_API_SECRET", "local-dev-secret"),
        python_runner_base_url=os.getenv("PYTHON_RUNNER_BASE_URL", "http://pbn:8081"),
    )


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
