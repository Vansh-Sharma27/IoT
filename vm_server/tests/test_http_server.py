"""End-to-end HTTP test: build the FastAPI app in-process with a stubbed
pipeline, then drive it via FastAPI's TestClient. Verifies auth, ping,
list, enroll, and authenticate.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from protocol import Decision
from vm_server.config import load_config
from vm_server.db.face_db import EMBEDDING_DIM, FaceDB
from vm_server.http_server import build_app
from vm_server.services import pipeline


TOKEN = "test-token-abcdef"


def _jpeg_bytes(seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, size=(120, 120, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


class _StubYolo:
    def __init__(self, n): self.n = n
    def predict(self, *a, **k):
        class R:
            def __init__(self, n):
                self.boxes = type("B", (), {"__len__": lambda self: n})()
        return [R(self.n)]


class _StubFace:
    def __init__(self, emb):
        self.bbox = [0, 0, 100, 100]
        self.normed_embedding = emb


class _StubFaceApp:
    def __init__(self, faces): self._faces = faces
    def get(self, img): return self._faces


@pytest.fixture()
def cfg(tmp_path):
    base = load_config()
    object.__setattr__(base, "repo_root", tmp_path)
    object.__setattr__(base.server, "secret_token", TOKEN)
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
def client(cfg, monkeypatch, known_emb):
    monkeypatch.setattr(pipeline, "_yolo", None, raising=False)
    monkeypatch.setattr(pipeline, "_face_app", None, raising=False)
    monkeypatch.setattr(pipeline, "_load_yolo", lambda c: _StubYolo(1))
    monkeypatch.setattr(
        pipeline, "_load_face_app", lambda c: _StubFaceApp([_StubFace(known_emb)])
    )
    monkeypatch.setattr(pipeline, "warm_up", lambda c: None)

    db = FaceDB(cfg.db_path)
    db.enroll("Alice", "allowed", known_emb)
    app = build_app(cfg, db)
    with TestClient(app) as c:
        yield c
    db.close()


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_ping_no_auth_required(client):
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_authenticate_requires_token(client):
    r = client.post("/authenticate", content=_jpeg_bytes())
    assert r.status_code == 401


def test_authenticate_rejects_bad_token(client):
    r = client.post(
        "/authenticate",
        content=_jpeg_bytes(),
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 403


def test_authenticate_known_face(client):
    r = client.post("/authenticate", content=_jpeg_bytes(), headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == Decision.ALLOWED.value
    assert body["name"] == "Alice"


def test_known_lists_enrolled(client):
    r = client.get("/known", headers=_auth())
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"


def test_authenticate_empty_body_400(client):
    r = client.post("/authenticate", content=b"", headers=_auth())
    assert r.status_code == 400
