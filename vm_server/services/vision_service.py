"""RPyC service surface for the surveillance robot.

Exposes only the methods the Pi client needs. **Wire payloads are JSON
strings**, not Python objects, so:
  - the Pi never has to call rpyc.classic.obtain (which requires pickling),
  - we can keep ``allow_pickle=False`` for safety,
  - the protocol is portable if we ever add a non-Python client.

All methods are thread-safe: ``FaceDB`` uses a single SQLite connection in
WAL-equivalent serialised mode, and pipeline.authenticate guards model loads
with a lock.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import rpyc

from vm_server.config import Config
from vm_server.db.face_db import FaceDB
from vm_server.services import pipeline

log = logging.getLogger(__name__)


class VisionService(rpyc.Service):
    cfg: Optional[Config] = None
    db: Optional[FaceDB] = None

    @classmethod
    def bind(cls, cfg: Config, db: FaceDB) -> None:
        cls.cfg = cfg
        cls.db = db

    def on_connect(self, conn):
        log.info("client connected: %s", conn)

    def on_disconnect(self, conn):
        log.info("client disconnected: %s", conn)

    def exposed_ping(self) -> str:
        return "ok"

    def exposed_authenticate(self, jpeg_bytes: bytes) -> str:
        assert self.cfg is not None and self.db is not None, "service not bound"
        local_bytes = bytes(jpeg_bytes)
        result = pipeline.authenticate(self.cfg, self.db, local_bytes)
        log.info(
            "authenticate -> %s (name=%s sim=%s reason=%s)",
            result.decision.value, result.name, result.similarity, result.reason,
        )
        return json.dumps(result.to_dict())

    def exposed_enroll(
        self, name: str, role: str, jpeg_bytes: bytes, photo_filename: str = ""
    ) -> str:
        assert self.cfg is not None and self.db is not None, "service not bound"
        local_bytes = bytes(jpeg_bytes)
        emb = pipeline.embed_image(self.cfg, local_bytes)
        if emb is None:
            return json.dumps({"ok": False, "error": "no_face_in_image"})

        photo_path: Optional[str] = None
        if photo_filename:
            self.cfg.photos_dir.mkdir(parents=True, exist_ok=True)
            dst = self.cfg.photos_dir / Path(photo_filename).name
            with open(dst, "wb") as f:
                f.write(local_bytes)
            photo_path = str(dst)

        try:
            face_id = self.db.enroll(name=name, role=role, embedding=emb, photo_path=photo_path)
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})
        return json.dumps({"ok": True, "id": face_id})

    def exposed_list_known(self) -> str:
        assert self.db is not None, "service not bound"
        rows = [
            {
                "id": r.id,
                "name": r.name,
                "role": r.role,
                "photo_path": r.photo_path,
                "created_at": r.created_at,
            }
            for r in self.db.list_all()
        ]
        return json.dumps(rows)

    def exposed_delete(self, face_id: int) -> bool:
        assert self.db is not None, "service not bound"
        return self.db.delete(int(face_id))
