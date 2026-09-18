from __future__ import annotations

import json
import logging
import signal
import threading
from pathlib import Path

from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .api_client import BackendInternalClient
from .config import WorkerConfig
from .events import EventPublisher
from .jobs import JobProcessor
from .runner_client import PythonRunnerClient

logger = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/pbn-worker-heartbeat")

def create_redis_client(config: WorkerConfig) -> Redis:
    return Redis(
        host=config.redis_addr,
        port=config.redis_port,
        db=config.redis_db,
        password=config.redis_password,
        decode_responses=True,
    )


def worker_loop(worker_name: str, config: WorkerConfig, stopping: threading.Event) -> None:
    redis_client = create_redis_client(config)
    backend = BackendInternalClient(config)
    runner = PythonRunnerClient(config)
    events = EventPublisher(redis_client, config)
    processor = JobProcessor(redis_client, config, backend, runner, events)

    logger.info("worker started: %s", worker_name)

    while not stopping.is_set():
        try:
            if not runner.is_ready():
                logger.info("runner is not ready; waiting before consuming jobs")
                stopping.wait(2)
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
            stopping.wait(2)
        except Exception:
            logger.exception("worker loop error")
            stopping.wait(2)

    redis_client.close()


def start_workers(config: WorkerConfig) -> None:
    if config.concurrency < 1:
        raise ValueError("WORKER_CONCURRENCY must be at least 1")
    stopping = threading.Event()

    def stop(signum: int, _frame: object) -> None:
        logger.info("received signal %s; finishing active jobs before exit", signum)
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threads: list[threading.Thread] = []

    for i in range(config.concurrency):
        thread = threading.Thread(
            target=worker_loop,
            args=(f"worker-{i + 1}", config, stopping),
            daemon=False,
        )
        thread.start()
        threads.append(thread)

    while any(thread.is_alive() for thread in threads):
        if all(thread.is_alive() for thread in threads):
            HEARTBEAT_PATH.touch()
        for thread in threads:
            thread.join(timeout=1)
