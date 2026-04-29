"""Tests for pipeline.authenticate using mocked YOLO and InsightFace.

These tests don't require model downloads — we monkeypatch the loader functions
to return stubs with the same interface InsightFace/ultralytics expose.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from protocol import Decision
from vm_server.config import load_config
from vm_server.db.face_db import EMBEDDING_DIM, FaceDB
from vm_server.services import pipeline


@dataclass
class _Box:
    pass


class _BoxList:
    def __init__(self, n: int):
        self._n = n

    def __len__(self):
        return self._n


class _YoloResult:
    def __init__(self, n: int):
        self.boxes = _BoxList(n)


class _StubYolo:
    def __init__(self, n_persons: int):
        self.n = n_persons

    def predict(self, img, classes=None, conf=None, verbose=False):
        return [_YoloResult(self.n)]


class _StubFace:
    def __init__(self, bbox, emb):
        self.bbox = bbox
        self.normed_embedding = emb


class _StubFaceApp:
    def __init__(self, faces):
        self._faces = faces

    def get(self, img):
        return self._faces


def _jpeg_bytes() -> bytes:
    import cv2
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _rand_emb(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    # Point the config at a tmp dir so we don't touch the real DB / models.
    base = load_config()
    object.__setattr__(base, "repo_root", tmp_path)
    base.db_path.parent.mkdir(parents=True, exist_ok=True)
    base.photos_dir.mkdir(parents=True, exist_ok=True)
    base.models_dir.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture()
def db(cfg):
    return FaceDB(cfg.db_path)


@pytest.fixture(autouse=True)
def reset_pipeline_globals(monkeypatch):
    monkeypatch.setattr(pipeline, "_yolo", None, raising=False)
    monkeypatch.setattr(pipeline, "_face_app", None, raising=False)


def test_non_human_when_no_person(cfg, db, monkeypatch):
    monkeypatch.setattr(pipeline, "_load_yolo", lambda c: _StubYolo(0))
    monkeypatch.setattr(pipeline, "_load_face_app", lambda c: _StubFaceApp([]))
    result = pipeline.authenticate(cfg, db, _jpeg_bytes())
    assert result.decision == Decision.NON_HUMAN


def test_unknown_when_person_but_no_face(cfg, db, monkeypatch):
    monkeypatch.setattr(pipeline, "_load_yolo", lambda c: _StubYolo(1))
    monkeypatch.setattr(pipeline, "_load_face_app", lambda c: _StubFaceApp([]))
    result = pipeline.authenticate(cfg, db, _jpeg_bytes())
    assert result.decision == Decision.UNKNOWN
    assert result.reason == "no_face"


def test_denied_when_face_not_in_db(cfg, db, monkeypatch):
    monkeypatch.setattr(pipeline, "_load_yolo", lambda c: _StubYolo(1))
    monkeypatch.setattr(
        pipeline,
        "_load_face_app",
        lambda c: _StubFaceApp([_StubFace([0, 0, 100, 100], _rand_emb(42))]),
    )
    result = pipeline.authenticate(cfg, db, _jpeg_bytes())
    assert result.decision == Decision.DENIED
    assert result.reason == "unknown_face"


def test_allowed_when_face_in_db_as_allowed(cfg, db, monkeypatch):
    emb = _rand_emb(7)
    db.enroll("Alice", "allowed", emb)
    monkeypatch.setattr(pipeline, "_load_yolo", lambda c: _StubYolo(1))
    monkeypatch.setattr(
        pipeline,
        "_load_face_app",
        lambda c: _StubFaceApp([_StubFace([0, 0, 100, 100], emb)]),
    )
    result = pipeline.authenticate(cfg, db, _jpeg_bytes())
    assert result.decision == Decision.ALLOWED
    assert result.name == "Alice"
    assert result.similarity == pytest.approx(1.0, abs=1e-5)


def test_denied_when_face_in_db_as_restricted(cfg, db, monkeypatch):
    emb = _rand_emb(8)
    db.enroll("Mallory", "restricted", emb)
    monkeypatch.setattr(pipeline, "_load_yolo", lambda c: _StubYolo(1))
    monkeypatch.setattr(
        pipeline,
        "_load_face_app",
        lambda c: _StubFaceApp([_StubFace([0, 0, 100, 100], emb)]),
    )
    result = pipeline.authenticate(cfg, db, _jpeg_bytes())
    assert result.decision == Decision.DENIED
    assert result.reason == "restricted_role"
    assert result.name == "Mallory"


def test_largest_face_picked(cfg, db, monkeypatch):
    emb_small = _rand_emb(1)
    emb_big = _rand_emb(2)
    db.enroll("Big", "allowed", emb_big)
    monkeypatch.setattr(pipeline, "_load_yolo", lambda c: _StubYolo(1))
    monkeypatch.setattr(
        pipeline,
        "_load_face_app",
        lambda c: _StubFaceApp(
            [
                _StubFace([0, 0, 30, 30], emb_small),    # area 900
                _StubFace([0, 0, 200, 200], emb_big),    # area 40000
            ]
        ),
    )
    result = pipeline.authenticate(cfg, db, _jpeg_bytes())
    assert result.decision == Decision.ALLOWED
    assert result.name == "Big"


def test_unknown_when_jpeg_bad(cfg, db, monkeypatch):
    # No model load should happen for bad JPEG.
    def boom(*a, **k):
        raise AssertionError("model loader called for bad JPEG")
    monkeypatch.setattr(pipeline, "_load_yolo", boom)
    monkeypatch.setattr(pipeline, "_load_face_app", boom)
    result = pipeline.authenticate(cfg, db, b"not a jpeg")
    assert result.decision == Decision.UNKNOWN
    assert result.reason == "bad_jpeg"
