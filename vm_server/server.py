"""RPyC server entrypoint for the VM-side vision service.

Usage:
    python -m vm_server.server                 # uses vm_server/config.yaml
    VM_CONFIG=/path/to/other.yaml python -m vm_server.server

Bound to the host/port from config (default 0.0.0.0:18861). Tailscale +
``ufw allow in on tailscale0 to any port 18861`` should be the only path
that can reach this; do NOT expose 18861 publicly.
"""

from __future__ import annotations

import logging
import signal
import sys

from rpyc.utils.server import ThreadedServer

from vm_server.config import load_config
from vm_server.db.face_db import FaceDB
from vm_server.services import pipeline
from vm_server.services.vision_service import VisionService

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    log.info(
        "loaded config: db=%s threshold=%.3f host=%s port=%d",
        cfg.db_path, cfg.matching.threshold, cfg.server.host, cfg.server.port,
    )
    db = FaceDB(cfg.db_path)
    log.info("face DB has %d enrolled identities", len(db.list_all()))

    log.info("warming up models (first authenticate would otherwise be slow)...")
    pipeline.warm_up(cfg)
    log.info("models ready")

    VisionService.bind(cfg, db)

    server = ThreadedServer(
        VisionService,
        hostname=cfg.server.host,
        port=cfg.server.port,
        protocol_config={
            "allow_public_attrs": False,
            "sync_request_timeout": cfg.server.sync_request_timeout,
        },
    )

    def _shutdown(signum, frame):
        log.info("signal %d received, stopping server", signum)
        server.close()
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("RPyC VisionService listening on %s:%d", cfg.server.host, cfg.server.port)
    server.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
