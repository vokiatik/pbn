from __future__ import annotations

import json
import logging

from redis import Redis

from .config import WorkerConfig
from .types import JsonDict

logger = logging.getLogger(__name__)


class EventPublisher:
    def __init__(self, redis_client: Redis, config: WorkerConfig) -> None:
        self.redis_client = redis_client
        self.config = config

    def publish(self, payload: JsonDict) -> None:
        try:
            subscriber_count = self.redis_client.publish(
                self.config.events_channel,
                json.dumps(payload),
            )
            files = payload.get("files")
            logger.info(
                "published redis event channel=%s type=%s project_id=%s status=%s step=%s file_count=%s subscribers=%s",
                self.config.events_channel,
                payload.get("type"),
                payload.get("project_id"),
                payload.get("status"),
                payload.get("step"),
                len(files) if isinstance(files, list) else 0,
                subscriber_count,
            )
        except Exception:
            logger.exception("failed to publish redis event")
