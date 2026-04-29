"""One-shot weight downloader.

Run once on a fresh VM:
    python -m vm_server.bootstrap_models

Triggers InsightFace and Ultralytics to fetch their respective ONNX/PT files
into ``vm_server/models/``. Subsequent runs are no-ops once the cache is warm.
"""

from __future__ import annotations

import logging
import sys

from vm_server.config import load_config
from vm_server.services import pipeline


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config()
    cfg.models_dir.mkdir(parents=True, exist_ok=True)
    logging.info("downloading / loading models into %s", cfg.models_dir)
    pipeline.warm_up(cfg)
    logging.info("models ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
