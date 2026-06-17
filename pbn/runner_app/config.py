import logging
import os
from pathlib import Path

import pillow_heif

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

pillow_heif.register_heif_opener()

PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", "/storage/projects"))

SAM2_CHECKPOINT = os.getenv(
    "SAM2_CHECKPOINT",
    "/app/checkpoints/sam2.1_hiera_base_plus.pt",
)

SAM2_MODEL_CFG = os.getenv(
    "SAM2_MODEL_CFG",
    "configs/sam2.1/sam2.1_hiera_b+.yaml",
)
