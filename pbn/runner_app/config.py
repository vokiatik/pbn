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
