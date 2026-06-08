from __future__ import annotations

import argparse
import logging
from pathlib import Path

from pbn.pbn_config import load_config
from pbn.pipeline import PBNPipeline


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate paint-by-number files from an image")
    parser.add_argument("input", type=Path, help="Input image path (jpg, png, webp)")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"), help="YAML config path")
    parser.add_argument("--out", type=Path, default=Path("output"), help="Output directory")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logging level")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_config(args.config)
    pipeline = PBNPipeline(cfg)
    outputs = pipeline.run(args.input, args.out)

    logging.info("Generated files:")
    for key, value in outputs.items():
        logging.info("%s: %s", key, value)


if __name__ == "__main__":
    main()
