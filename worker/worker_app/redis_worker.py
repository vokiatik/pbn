from __future__ import annotations

import json
import logging
import threading
import time

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .api_client import BackendInternalClient
from .config import WorkerConfig
from .events import EventPublisher
from .jobs import JobProcessor
from .runner_client import PythonRunnerClient

logger = logging.getLogger(__name__)

def create_redis_client(config: WorkerConfig) -> Redis:
    return Redis(
        host=config.redis_addr,
        port=config.redis_port,
        db=config.redis_db,
        password=config.redis_password,
        decode_responses=True,
    )


def worker_loop(worker_name: str, config: WorkerConfig) -> None:
    redis_client = create_redis_client(config)
    backend = BackendInternalClient(config)
    runner = PythonRunnerClient(config)
    events = EventPublisher(redis_client, config)
    processor = JobProcessor(redis_client, config, backend, runner, events)

    logger.info("worker started: %s", worker_name)

    while True:
        try:
            if not runner.is_ready():
                logger.info("runner is not ready; waiting before consuming jobs")
                time.sleep(2)
                continue
            item = redis_client.blpop(config.queue_name, timeout=5)
            if not item:
                continue

            _, raw_payload = item
            payload = json.loads(raw_payload)
            processor.process(payload)

        except RedisTimeoutError:
            continue
        except RedisConnectionError:
            logger.warning("redis connection issue in worker loop; retrying")
            time.sleep(2)
        except Exception:
            logger.exception("worker loop error")
            time.sleep(2)


def start_workers(config: WorkerConfig) -> None:
    threads: list[threading.Thread] = []

    for i in range(config.concurrency):
        thread = threading.Thread(
            target=worker_loop,
            args=(f"worker-{i + 1}", config),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()
