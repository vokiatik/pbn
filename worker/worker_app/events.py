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
            self.redis_client.publish(self.config.events_channel, json.dumps(payload))
        except Exception:
            logger.exception("failed to publish redis event")
