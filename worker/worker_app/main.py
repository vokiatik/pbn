from __future__ import annotations

from .config import load_config, setup_logging
from .redis_worker import start_workers


def main() -> None:
    setup_logging()
    config = load_config()
    start_workers(config)


if __name__ == "__main__":
    main()
