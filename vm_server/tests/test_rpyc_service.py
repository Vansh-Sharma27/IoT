"""End-to-end RPyC test: spin up VisionService in-process, connect a client,
verify ping/list/enroll/authenticate using monkeypatched models.
"""

from __future__ import annotations

import threading
import time
from contextlib import closing

import cv2
import numpy as np
import pytest
import rpyc
from rpyc.utils.server import ThreadedServer

from protocol import Decision
from vm_server.config import load_config
from vm_server.db.face_db import EMBEDDING_DIM, FaceDB
from vm_server.services import pipeline
from vm_server.services.vision_service import VisionService


def _jpeg_bytes(seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, size=(120, 120, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _free_port() -> int:
    import socket
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _StubYolo:
    def __init__(self, n): self.n = n
    def predict(self, *a, **k):
        class R:
            def __init__(self, n):
                self.boxes = type("B", (), {"__len__": lambda self: n})()
        return [R(self.n)]


class _StubFace:
    def __init__(self, emb): self.bbox = [0, 0, 100, 100]; self.normed_embedding = emb


class _StubFaceApp:
    def __init__(self, faces): self._faces = faces
    def get(self, img): return self._faces


@pytest.fixture()
def cfg(tmp_path):
    base = load_config()
    object.__setattr__(base, "repo_root", tmp_path)
    base.db_path.parent.mkdir(parents=True, exist_ok=True)
    base.photos_dir.mkdir(parents=True, exist_ok=True)
    base.models_dir.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture()
def known_emb():
    rng = np.random.default_rng(123)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture()
def server(cfg, monkeypatch, known_emb):
    monkeypatch.setattr(pipeline, "_yolo", None, raising=False)
    monkeypatch.setattr(pipeline, "_face_app", None, raising=False)
    monkeypatch.setattr(pipeline, "_load_yolo", lambda c: _StubYolo(1))
    monkeypatch.setattr(
        pipeline, "_load_face_app", lambda c: _StubFaceApp([_StubFace(known_emb)])
    )

    db = FaceDB(cfg.db_path)
    db.enroll("Alice", "allowed", known_emb)
    VisionService.bind(cfg, db)

    port = _free_port()
    srv = ThreadedServer(
        VisionService,
        hostname="127.0.0.1",
        port=port,
        protocol_config={"allow_public_attrs": False, "sync_request_timeout": 5},
    )
    t = threading.Thread(target=srv.start, daemon=True)
    t.start()
    for _ in range(50):
        try:
            rpyc.connect("127.0.0.1", port).close()
            break
        except ConnectionRefusedError:
            time.sleep(0.05)
    yield port
    srv.close()
    db.close()


def test_ping(server):
    conn = rpyc.connect("127.0.0.1", server)
    try:
        assert conn.root.ping() == "ok"
    finally:
        conn.close()


def test_authenticate_known_face(server):
    import json
    conn = rpyc.connect("127.0.0.1", server)
    try:
        result = json.loads(conn.root.authenticate(_jpeg_bytes()))
        assert result["decision"] == Decision.ALLOWED.value
        assert result["name"] == "Alice"
    finally:
        conn.close()


def test_list_known(server):
    import json
    conn = rpyc.connect("127.0.0.1", server)
    try:
        rows = json.loads(conn.root.list_known())
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice"
    finally:
        conn.close()
