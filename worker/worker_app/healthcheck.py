"""Probe the live worker supervisor and its authenticated queue connection."""
import time

from .config import load_config
from .redis_worker import HEARTBEAT_PATH, create_redis_client


def main() -> None:
    if time.time() - HEARTBEAT_PATH.stat().st_mtime > 90:
        raise SystemExit(1)
    config = load_config()
    with create_redis_client(config) as client:
        if not client.ping():
            raise SystemExit(1)


if __name__ == "__main__":
    main()
